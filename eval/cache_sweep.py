"""Phase 4 cache threshold sweep on the 25-item subset (EVAL_RESULTS.md, Phase 4).

    uv run python eval/cache_sweep.py --check            # workload checks; no LLM
    uv run python eval/cache_sweep.py --record           # 25 real generations, cache off -> recording
    uv run python eval/cache_sweep.py --sweep            # every threshold, replaying the recording; no LLM
    uv run python eval/cache_sweep.py --judge SWEEP.json # judge each distinct served answer once
    uv run python eval/cache_sweep.py --report SWEEP.json

Workload per threshold, cache cleared first:
- Phase A (cold): the 25 subset questions. Nothing can hit; measures the lookup's cost on the miss path.
- Phase B (warm), immediately after: the 25 again, then for each one an exact repeat, a case/punctuation
  variant and a genuine paraphrase (eval/cache_workload.jsonl, written before any run).

The real model answers each subset question ONCE (--record). The sweep replays those recorded answers on
misses: the cache's decisions (hit or miss, which entry) do not depend on generated text, and every
answer a hit can serve is the recorded real answer of the item's own question (asserted per hit). A
variant or paraphrase that misses is stored with its item's recorded answer; in this workload order no
later request can be served such an entry ahead of the original's. Miss latency therefore excludes the
model; the recorded real LLM latency is reported beside it.

Hard gate at every threshold: the full cache isolation suite (`pytest tests/test_cache_isolation.py
--cache-threshold T`), which includes all five near-miss pairs, must pass; and within the workload no hit
may serve another item's answer. A threshold that fails either is not a candidate.
"""

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import httpx
from openai.types.chat import ChatCompletionMessageParam

from gateway.cache.semantic import CacheConfig, content_key
from gateway.config import Settings, get_settings
from gateway.deps import auth_for_email
from gateway.llm.prompts import PROMPT_VERSION
from gateway.llm.provider import Completion, OpenAICompatibleLLM
from gateway.main import create_app
from gateway.retrieval.vector import vector_search
from gateway.security.tokens import issue_token
from judge import Source
from run_eval import (
    RESULTS_DIR,
    ROOT,
    HarnessStopped,
    judge_and_log,
    load_golden,
    preflight,
    require_stack,
    select_subset,
)

WORKLOAD = Path(__file__).resolve().parent / "cache_workload.jsonl"
RECORDING = RESULTS_DIR / "cache_sweep_recording.json"
SWEEP = (0.88, 0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99)
KINDS = ("rerun", "exact", "variant", "paraphrase")


def load_workload() -> list[dict[str, Any]]:
    rows = [json.loads(x) for x in WORKLOAD.read_text(encoding="utf-8").splitlines() if x.strip()]
    gold = {g["id"]: g for g in select_subset(load_golden(), 25)}
    if [r["id"] for r in rows] != list(gold):
        raise SystemExit("cache_workload.jsonl does not match the fixed 25-item subset")
    return [{**gold[r["id"]], **r} for r in rows]


def p50(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


async def check(settings: Settings) -> int:
    from gateway.ingest.embedder import Embedder

    items = load_workload()
    emb = Embedder(settings.embedding_model_id, settings.embedding_dim, settings.embedding_cache_dir)
    cfg = CacheConfig.from_patterns(0.95, 24, settings.cache_bypass_patterns)
    problems, rows = [], []
    for i in items:
        q, v, p = i["question"], i["variant"], i["paraphrase"]
        if content_key(v) != content_key(q):
            problems.append(f"{i['id']}: variant changes the content words")
        vq, vv, vp = [await emb.embed_query(x) for x in (q, v, p)]
        cos_v = sum(a * b for a, b in zip(vq, vv, strict=True))
        cos_p = sum(a * b for a, b in zip(vq, vp, strict=True))
        rows.append(
            (i["id"], round(cos_v, 4), round(cos_p, 4), content_key(p) == content_key(q), cfg.bypassed(q))
        )
    print("id    cos(variant) cos(paraphrase) paraphrase-same-words bypassed")
    for r in rows:
        print(f"{r[0]}  {r[1]:.4f}       {r[2]:.4f}          {r[3]!s:5}                 {r[4]}")
    print(
        f"variant cosine min {min(r[1] for r in rows):.4f}; paraphrase cosine range "
        f"{min(r[2] for r in rows):.4f}-{max(r[2] for r in rows):.4f}; "
        f"paraphrases sharing all content words: {sum(r[3] for r in rows)}"
    )
    if problems:
        print("\n".join(problems))
        return 1
    return 0


async def _ask(
    client: httpx.AsyncClient, pool: asyncpg.Pool, settings: Settings, item: dict[str, Any], question: str
) -> dict[str, Any]:
    async with pool.acquire() as conn:
        auth = await auth_for_email(conn, item["tenant"], item["as_user"])
    token = issue_token(settings, user_id=auth.user_id, tenant_id=auth.tenant_id)
    started = time.perf_counter()
    r = await client.post(
        "/v1/query", json={"question": question}, headers={"Authorization": f"Bearer {token}"}
    )
    wall_ms = round((time.perf_counter() - started) * 1000)
    if r.status_code != 200:
        raise HarnessStopped(f"{item['id']}: /v1/query {r.status_code}: {r.text[:200]}")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT q.id, q.cache_hit, q.cache_lookup_ms, q.retrieval_ms, q.llm_ms, q.total_ms, q.outcome, "
            "q.answer_raw, q.model_used, a.served_from_cache FROM query_log q "
            "JOIN audit_log a ON a.query_log_id = q.id WHERE q.tenant_id = $1 ORDER BY q.id DESC LIMIT 1",
            auth.tenant_id,
        )
    body = r.json()
    return {
        **dict(row),
        "answer": body["answer"],
        "citations": [c["chunk_id"] for c in body["citations"]],
        "wall_ms": wall_ms,
    }


async def record(settings: Settings, force_budget: bool) -> int:
    items = load_workload()
    llm = OpenAICompatibleLLM(settings, settings.llm_tier)
    app = create_app(settings.model_copy(update={"cache_enabled": False}), llm=llm)
    out: dict[str, Any] = {}
    async with app.router.lifespan_context(app):
        pool = app.state.pool
        async with pool.acquire() as conn:
            over = await preflight(
                conn, settings.llm_daily_token_limit, {llm.model_id: [("query", len(items))]}
            )
        if over and not force_budget:
            print("pre-flight: the recording does not fit today's generator budget; not starting")
            return 1
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://s", timeout=180
        ) as c:
            for n, i in enumerate(items, 1):
                res = await _ask(c, pool, settings, i, i["question"])
                async with pool.acquire() as conn:
                    auth = await auth_for_email(conn, i["tenant"], i["as_user"])
                    top = await vector_search(
                        conn,
                        acl_filter=auth.acl(),
                        query_embedding=await app.state.embedder.embed_query(i["question"]),
                        top_k=settings.retrieval_top_k,
                    )
                out[i["id"]] = {
                    "answer_raw": res["answer_raw"],
                    "answer": res["answer"],
                    "outcome": res["outcome"],
                    "citations": res["citations"],
                    "model": res["model_used"],
                    "llm_ms": res["llm_ms"],
                    "sources": [{"title": t.document_title, "content": t.content} for t in top],
                }
                print(f"  [{n}/{len(items)}] {i['id']} {res['outcome']} llm {res['llm_ms']} ms", flush=True)
                await asyncio.sleep(settings.eval_request_delay_ms / 1000)
    await llm.aclose()
    meta = {
        "recorded_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": llm.model_id,
        "prompt_version": PROMPT_VERSION,
        "top_k": settings.retrieval_top_k,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    RECORDING.write_text(json.dumps({"meta": meta, "items": out}, indent=1), encoding="utf-8")
    print(f"recording: {RECORDING}")
    return 0


class ReplayLLM:
    """Returns the recorded real answer of the item being asked (set before each request)."""

    tier = "small"

    def __init__(self, recording: dict[str, Any]) -> None:
        self.items = recording["items"]
        self.model_id = recording["meta"]["model"]
        self.current = ""

    async def complete(self, messages: list[ChatCompletionMessageParam]) -> Completion:
        rec = self.items[self.current]
        return Completion(rec["answer_raw"] or "", rec["model"] or self.model_id, None, None)


def _gate(threshold: float) -> bool:
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/test_cache_isolation.py",
            f"--cache-threshold={threshold}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:]
    print(f"    isolation suite at {threshold}: {last}")
    return r.returncode == 0


async def sweep(settings: Settings) -> int:
    if not RECORDING.exists():
        raise SystemExit("no recording; run --record first")
    recording = json.loads(RECORDING.read_text(encoding="utf-8"))
    items = load_workload()
    llm = ReplayLLM(recording)
    app = create_app(settings.model_copy(update={"cache_enabled": True}), llm=llm)  # type: ignore[arg-type]
    results: dict[str, Any] = {"thresholds": {}, "baseline_no_cache": []}
    async with app.router.lifespan_context(app):
        pool, base = app.state.pool, app.state.cache
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://s", timeout=60
        ) as c:
            # Lookup overhead reference: the cold questions with the cache off.
            app.state.cache = None
            for i in items:
                llm.current = i["id"]
                results["baseline_no_cache"].append(await _ask(c, pool, settings, i, i["question"]))
            for t in SWEEP:
                async with pool.acquire() as conn:
                    await conn.execute("DELETE FROM semantic_cache")
                app.state.cache = CacheConfig(t, base.ttl_hours, base.bypass_patterns)
                runs: list[dict[str, Any]] = []
                plan = [("cold", i, i["question"]) for i in items] + [
                    (
                        k,
                        i,
                        {
                            "rerun": i["question"],
                            "exact": i["question"],
                            "variant": i["variant"],
                            "paraphrase": i["paraphrase"],
                        }[k],
                    )
                    for k in KINDS
                    for i in items
                ]
                for kind, i, q in plan:
                    llm.current = i["id"]
                    res = await _ask(c, pool, settings, i, q)
                    own = recording["items"][i["id"]]
                    wrong = bool(res["served_from_cache"]) and (
                        res["answer"] != own["answer"] or res["citations"] != own["citations"]
                    )
                    runs.append(
                        {
                            "kind": kind,
                            "id": i["id"],
                            "type": i["type"],
                            "question": q,
                            **res,
                            "served_wrong_item": wrong,
                        }
                    )
                gate = _gate(t)
                results["thresholds"][str(t)] = {"runs": runs, "isolation_suite_passed": gate}
                hits = {k: sum(1 for r in runs if r["kind"] == k and r["served_from_cache"]) for k in KINDS}
                print(
                    f"  {t}: hits {hits} wrong-item {sum(r['served_wrong_item'] for r in runs)} gate {gate}",
                    flush=True,
                )
    results["meta"] = {
        "swept_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "recording": recording["meta"],
        "thresholds": list(SWEEP),
    }
    out = RESULTS_DIR / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_cache_sweep.json"
    out.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"sweep: {out}")
    return 0


def served_pairs(results: dict[str, Any]) -> list[tuple[str, str]]:
    """Distinct (item id, asked question) pairs served from the cache at any threshold."""
    seen: dict[tuple[str, str], None] = {}
    for th in results["thresholds"].values():
        for r in th["runs"]:
            if r["served_from_cache"]:
                seen[(r["id"], r["question"])] = None
    return list(seen)


def read_verdicts(verdict_file: Path) -> dict[tuple[str, str], dict[str, Any] | None]:
    if not verdict_file.exists():
        return {}
    rows = (json.loads(x) for x in verdict_file.read_text(encoding="utf-8").splitlines() if x.strip())
    return {(v["id"], v["question"]): v.get("judge") for v in rows}


def load_judge_inputs(sweep_file: Path) -> tuple[dict[str, Any], dict[str, Any], set[tuple[str, str]]]:
    results = json.loads(sweep_file.read_text(encoding="utf-8"))
    recording = json.loads(RECORDING.read_text(encoding="utf-8"))
    return results, recording, set(read_verdicts(sweep_file.with_suffix(".verdicts.jsonl")))


async def judge(settings: Settings, sweep_file: Path, force_budget: bool) -> int:
    results, recording, done = load_judge_inputs(sweep_file)
    items = {i["id"]: i for i in load_workload()}
    verdict_file = sweep_file.with_suffix(".verdicts.jsonl")
    todo = [p for p in served_pairs(results) if p not in done]
    print(f"{len(served_pairs(results))} distinct served answers; {len(todo)} to judge")
    judge_llm = OpenAICompatibleLLM(
        settings.model_copy(update={"llm_max_completion_tokens": settings.eval_judge_max_completion_tokens}),
        settings.eval_judge_tier,
    )
    app = create_app(settings.model_copy(update={"cache_enabled": False}), llm=judge_llm)
    async with app.router.lifespan_context(app):
        pool = app.state.pool
        async with pool.acquire() as conn:
            over = await preflight(
                conn, settings.llm_daily_token_limit, {judge_llm.model_id: [("eval_judge", len(todo))]}
            )
        if over and not force_budget:
            print("pre-flight: judging does not fit today's judge budget; run again when the window allows")
            await judge_llm.aclose()
            return 1
        for n, (iid, question) in enumerate(todo, 1):
            i, rec = items[iid], recording["items"][iid]
            async with pool.acquire() as conn:
                tenant_id = await conn.fetchval("SELECT id FROM tenants WHERE slug = $1", i["tenant"])
            sources = [Source(f"S{k}", s["title"], s["content"]) for k, s in enumerate(rec["sources"], 1)]
            out = await judge_and_log(
                pool,
                tenant_id,
                judge_llm,
                question,
                i["expected_answer"],
                sources,
                rec["answer"],
                settings.eval_request_delay_ms / 1000,
            )
            with verdict_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"id": iid, "question": question, **out}, default=str) + "\n")
            print(
                f"  [{n}/{len(todo)}] {iid} {out.get('judge', {}).get('correct', out.get('judge_error'))}",
                flush=True,
            )
    await judge_llm.aclose()
    return 0


def report(sweep_file: Path) -> int:
    results = json.loads(sweep_file.read_text(encoding="utf-8"))
    recording = json.loads(RECORDING.read_text(encoding="utf-8"))
    verdicts = read_verdicts(sweep_file.with_suffix(".verdicts.jsonl"))
    base = results["baseline_no_cache"]
    llm_ms = [r["llm_ms"] for r in recording["items"].values() if r["llm_ms"]]
    cacheable = {iid for iid, r in recording["items"].items() if r["outcome"] == "answered"}
    print(f"cacheable items (answered when recorded): {len(cacheable)}/25")
    print(f"recorded real LLM p50 {p50(llm_ms)} ms")
    print(f"no-cache cold retrieval p50 {p50([r['retrieval_ms'] for r in base])} ms")
    print(
        "| threshold | exact | variant | paraphrase | rerun | served answers judged faithful / correct "
        "| p50 hit ms | p50 miss ms (no LLM) | lookup p50 on cold misses | wrong-item hits "
        "| isolation suite |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for t, th in results["thresholds"].items():
        runs = th["runs"]
        rate = {k: f"{sum(r['served_from_cache'] for r in runs if r['kind'] == k)}/25" for k in KINDS}
        served = [verdicts.get((r["id"], r["question"])) for r in runs if r["served_from_cache"]]
        judged = [v for v in served if v]
        faith = f"{sum(v['faithful'] for v in judged)}/{len(judged)}" if judged else "pending"
        corr = f"{sum(v['correct'] for v in judged)}/{len(judged)}" if judged else "pending"
        hit_ms = [r["total_ms"] for r in runs if r["served_from_cache"]]
        miss_ms = [r["total_ms"] for r in runs if not r["served_from_cache"]]
        lookup = [
            r["cache_lookup_ms"] for r in runs if r["kind"] == "cold" and r["cache_lookup_ms"] is not None
        ]
        print(
            f"| {t} | {rate['exact']} | {rate['variant']} | {rate['paraphrase']} | {rate['rerun']} | "
            f"{faith} / {corr} | {p50(hit_ms)} | {p50(miss_ms)} | {p50(lookup)} | "
            f"{sum(r['served_wrong_item'] for r in runs)} | "
            f"{'pass' if th['isolation_suite_passed'] else 'FAIL'} |"
        )
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--record", action="store_true")
    g.add_argument("--sweep", action="store_true")
    g.add_argument("--judge", type=Path, metavar="SWEEP_JSON")
    g.add_argument("--report", type=Path, metavar="SWEEP_JSON")
    ap.add_argument("--force-budget", action="store_true")
    ap.add_argument("--force-containers", action="store_true")
    a = ap.parse_args()
    if a.report:
        sys.exit(report(a.report))
    settings = get_settings()
    if not a.check:
        require_stack(strict=True, force_containers=a.force_containers)
    if a.check:
        sys.exit(asyncio.run(check(settings)))
    if a.record:
        sys.exit(asyncio.run(record(settings, a.force_budget)))
    if a.sweep:
        sys.exit(asyncio.run(sweep(settings)))
    sys.exit(asyncio.run(judge(settings, a.judge, a.force_budget)))


if __name__ == "__main__":
    main()
