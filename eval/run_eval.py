"""Golden-set evaluation harness (Phase 2).

    uv run python eval/run_eval.py --subset 25          # fixed stratified 25-item sample (iteration)
    uv run python eval/run_eval.py                      # full 100-item run
    uv run python eval/run_eval.py --baseline "Phase 2" # full run, recorded in EVAL_RESULTS.md
    uv run python eval/run_eval.py --retrieval-only     # retrieval metrics only, no LLM calls
    uv run python eval/run_eval.py --resume eval/results/<run>.partial.jsonl

Per question: vector retrieval at top 10 (the same search /v1/query uses) for retrieval metrics;
POST /v1/query in-process for the answer (writes query_log, including answer_raw); then one judge
call per non-refused answer. Every LLM call is followed by EVAL_REQUEST_DELAY_MS. Records are
appended to a .partial.jsonl after each question, so a run stopped by rate limits can resume.
Results go to eval/results/<UTC stamp>_<mode>.json, labelled with the mode. Only full runs with
judging may become a baseline in EVAL_RESULTS.md (CLAUDE.md, Phase 2 rules).
"""

import argparse
import asyncio
import hashlib
import json
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import httpx

from gateway.config import Settings, get_settings
from gateway.errors import LLMProviderError
from gateway.llm.prompts import PROMPT_VERSION
from gateway.llm.provider import OpenAICompatibleLLM
from gateway.main import create_app
from gateway.rag import resolve_tenant
from gateway.retrieval.vector import RetrievedChunk, vector_search
from judge import JUDGE_PROMPT_VERSION, JudgeParseError, Source, judge
from metrics import all_hops_at_k, hop_ranks, ndcg_at_k, recall_at_k, reciprocal_rank

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
GOLDEN = EVAL_DIR / "golden_set.jsonl"
RESULTS_DIR = EVAL_DIR / "results"
BASELINES_DIR = EVAL_DIR / "baselines"
EVAL_RESULTS_MD = ROOT / "EVAL_RESULTS.md"

RETRIEVE_K = 10
SUBSET_SEED = "gateway-subset-v1"
# Fixed allocation for --subset 25, proportional to the full set (strata sizes 20/30/25/15/10).
# Near-miss items are drawn as whole pairs. Changing this changes the subset: bump SUBSET_SEED.
SUBSET_ALLOCATION = {
    25: {"buried_fact": 5, "single_other": 7, "multi_hop": 6, "unanswerable": 3, "near_miss_pairs": 2}
}


class HarnessStopped(Exception):
    """The run cannot continue (rate limit, provider failure); progress is saved in the partial file."""


def load_golden(path: Path = GOLDEN) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def golden_hash(path: Path = GOLDEN) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def stratum(item: dict[str, Any]) -> str:
    if item["type"] == "single_hop":
        return "buried_fact" if "buried_fact" in item["tags"] else "single_other"
    return str(item["type"])


def _key(name: str) -> str:
    return hashlib.sha256(f"{SUBSET_SEED}:{name}".encode()).hexdigest()


def select_subset(items: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    """Deterministic stratified sample: same ids every time for the same golden set and seed."""
    if size not in SUBSET_ALLOCATION:
        raise ValueError(f"--subset supports {sorted(SUBSET_ALLOCATION)} only (fixed, reproducible samples)")
    alloc = SUBSET_ALLOCATION[size]
    by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_stratum[stratum(item)].append(item)
    chosen: list[dict[str, Any]] = []
    for name in ("buried_fact", "single_other", "multi_hop", "unanswerable"):
        chosen += sorted(by_stratum[name], key=lambda i: _key(i["id"]))[: alloc[name]]
    pairs = sorted({i["pair"] for i in by_stratum["near_miss"]}, key=_key)[: alloc["near_miss_pairs"]]
    chosen += [i for i in by_stratum["near_miss"] if i["pair"] in pairs]
    ids = {i["id"] for i in chosen}
    return [i for i in items if i["id"] in ids]


def hops(item: dict[str, Any]) -> list[list[str]]:
    return [ev["chunk_ids"] for ev in item["evidence"]]


def retrieval_metrics(ranked: list[str], item: dict[str, Any]) -> dict[str, Any]:
    h = hops(item)
    return {
        "hop_ranks": hop_ranks(ranked, h),
        "recall@5": recall_at_k(ranked, h, 5),
        "recall@6": recall_at_k(ranked, h, 6),
        "recall@10": recall_at_k(ranked, h, 10),
        "all_hops@10": all_hops_at_k(ranked, h, 10),
        "mrr": reciprocal_rank(ranked, h),
        "ndcg@10": ndcg_at_k(ranked, h, 10),
    }


def _mean(values: Iterable[float]) -> float | None:
    vals = list(values)
    return round(statistics.mean(vals), 4) if vals else None


def _rate(flags: list[bool]) -> dict[str, Any]:
    return {
        "rate": round(sum(flags) / len(flags), 4) if flags else None,
        "n": len(flags),
        "count": sum(flags),
    }


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [r for r in records if r["type"] != "unanswerable"]
    groups: dict[str, list[dict[str, Any]]] = {"all_answerable": answerable}
    for r in answerable:
        groups.setdefault(r["type"], []).append(r)
        if "buried_fact" in r["tags"]:
            groups.setdefault("buried_fact", []).append(r)
    retrieval = {
        name: {
            "n": len(rs),
            **{
                m: _mean(r["retrieval"][m] for r in rs)
                for m in ("recall@5", "recall@6", "recall@10", "mrr", "ndcg@10")
            },
            "all_hops@10": _mean(float(r["retrieval"]["all_hops@10"]) for r in rs),
        }
        for name, rs in groups.items()
    }
    out: dict[str, Any] = {"retrieval": retrieval}
    generated = [r for r in records if "refused" in r]
    if generated:
        unanswerable = [r for r in generated if r["type"] == "unanswerable"]
        ans = [r for r in generated if r["type"] != "unanswerable"]
        judged = [r for r in generated if r.get("judge")]
        pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in ans:
            if r.get("pair"):
                pairs[r["pair"]].append(r)
        out["generation"] = {
            "correct_refusal_unanswerable": _rate([r["refused"] for r in unanswerable]),
            "false_refusal_answerable": _rate([r["refused"] for r in ans]),
            "faithful": _rate([r["judge"]["faithful"] for r in judged]),
            "relevant": _rate([r["judge"]["relevant"] for r in judged]),
            # Correctness over all answerable items: a refusal counts as not correct.
            "correct_answerable": _rate([bool(r.get("judge") and r["judge"]["correct"]) for r in ans]),
            "near_miss_pairs_both_correct": _rate(
                [all(bool(r.get("judge") and r["judge"]["correct"]) for r in rs) for rs in pairs.values()]
            ),
            "judge_errors": sum(1 for r in generated if r.get("judge_error")),
            "hallucinated_on_unanswerable": [r["id"] for r in unanswerable if not r["refused"]],
            "refused_answerable": [r["id"] for r in ans if r["refused"]],
        }
    return out


def git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT)
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT).stdout
    return result.stdout.strip() + ("-dirty" if dirty.strip() else "")


def mode_name(subset: int | None, retrieval_only: bool) -> str:
    base = f"subset{subset}" if subset else "full"
    return f"retrieval-{base}" if retrieval_only else base


async def resolve_gold_uuids(
    conn: asyncpg.Connection, items: list[dict[str, Any]]
) -> dict[tuple[str, str], str]:
    """Correction F: gold ids are slug#ordinal; resolve them to chunk UUIDs, failing on any stale id."""
    rows = await conn.fetch(
        """
        SELECT t.slug AS tenant, d.slug || '#' || c.ordinal AS gid, c.id::text AS uuid
        FROM chunks c JOIN documents d ON d.id = c.document_id JOIN tenants t ON t.id = c.tenant_id
        """
    )
    known = {(r["tenant"], r["gid"]): r["uuid"] for r in rows}
    stale = sorted({(i["tenant"], g) for i in items for g in i["gold_chunk_ids"]} - known.keys())
    if stale:
        raise SystemExit(f"stale gold ids (run eval/verify_golden.py): {stale[:5]}")
    return known


def gid(chunk: RetrievedChunk) -> str:
    return f"{chunk.document_slug}#{chunk.ordinal}"


async def evaluate_item(
    item: dict[str, Any],
    client: httpx.AsyncClient,
    pool: asyncpg.Pool,
    app_state: Any,
    judge_llm: OpenAICompatibleLLM | None,
    settings: Settings,
    delay_s: float,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        k: item.get(k)
        for k in ("id", "type", "tags", "tenant", "as_user", "pair", "question", "expected_answer")
    }
    async with pool.acquire() as conn:
        tenant_id = await resolve_tenant(conn, item["tenant"])
        query_vec = await app_state.embedder.embed_query(item["question"])
        chunks = await vector_search(conn, tenant_id=tenant_id, query_embedding=query_vec, top_k=RETRIEVE_K)
    ranked = [gid(c) for c in chunks]
    record["retrieved"] = ranked
    if item["type"] != "unanswerable":
        record["retrieval"] = retrieval_metrics(ranked, item)
    if judge_llm is None:  # retrieval-only run
        return record

    # Phase 2 has no auth: the tenant is named in the body (CLAUDE.md shortcut). as_user is recorded
    # so Phase 3 can switch this call to the seeded user's token.
    response = await client.post("/v1/query", json={"tenant": item["tenant"], "question": item["question"]})
    await asyncio.sleep(delay_s)
    if response.status_code != 200:
        raise HarnessStopped(
            f"{item['id']}: /v1/query returned {response.status_code}: {response.text[:300]}"
        )
    body = response.json()
    async with pool.acquire() as conn:
        record["query_log_id"] = await conn.fetchval(
            "SELECT max(id) FROM query_log WHERE tenant_id = $1", tenant_id
        )
    top = chunks[: settings.retrieval_top_k]
    by_uuid = {str(c.chunk_id): c for c in top}
    cited = [by_uuid.get(c["chunk_id"]) for c in body["citations"]]
    if any(c is None for c in cited):
        raise HarnessStopped(
            f"{item['id']}: answer cites chunks outside the harness's top {settings.retrieval_top_k}"
        )
    record.update(
        answer=body["answer"],
        refused=body["refused"],
        citations=[gid(c) for c in cited if c is not None],
        model=body["model"],
        prompt_version=body["prompt_version"],
        timings=body["timings"],
    )
    if body["refused"]:
        return record

    sources = [Source(f"S{n}", c.document_title, c.content) for n, c in enumerate(top, 1)]
    try:
        verdict, raw = await judge(
            judge_llm, item["question"], item["expected_answer"], sources, body["answer"]
        )
        record["judge"] = {**verdict.__dict__, "raw": raw}
    except JudgeParseError as exc:
        record["judge_error"] = str(exc)
    except LLMProviderError as exc:
        detail = exc.describe() if hasattr(exc, "describe") else str(exc)
        raise HarnessStopped(f"{item['id']}: judge call failed: {detail}") from exc
    finally:
        await asyncio.sleep(delay_s)
    return record


def write_baseline_section(label: str, result: dict[str, Any], baseline_file: Path) -> None:
    meta, agg = result["meta"], result["aggregate"]
    r, g = agg["retrieval"], agg["generation"]

    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x * 100:.1f}%"

    lines = [
        f"## Golden set baseline — {label}",
        "",
        f"Full run of all {meta['n_items']} golden-set items, {meta['finished_utc']}, by "
        f'`uv run python eval/run_eval.py --baseline "{label}"`. '
        f"Results: `{baseline_file.relative_to(ROOT)}`.",
        "",
        f"- Generator: `{meta['generator_model']}` (tier `{meta['llm_tier']}`), "
        f"prompt `{meta['prompt_version']}`; judge: `{meta['judge_model']}` (tier `{meta['judge_tier']}`), "
        f"prompt `{meta['judge_prompt_version']}`",
        "- Retrieval: vector-only, tenant-wide, no ACL filter; "
        f"answers use top {meta['top_k']}; metrics at top {meta['retrieve_k']}",
        f"- Golden set hash `{meta['golden_hash']}`; corpus {meta['corpus_chunks']} chunks; "
        f"commit `{meta['git_commit']}`",
        "",
        "| Retrieval (answerable items) | n | recall@5 | recall@6 | recall@10 | all-hops@10 | MRR "
        "| nDCG@10 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name in ("all_answerable", "single_hop", "buried_fact", "multi_hop", "near_miss"):
        if name in r:
            m = r[name]
            lines.append(
                f"| {name} | {m['n']} | {pct(m['recall@5'])} | {pct(m['recall@6'])} | {pct(m['recall@10'])} "
                f"| {pct(m['all_hops@10'])} | {m['mrr']:.3f} | {m['ndcg@10']:.3f} |"
            )
    lines += [
        "",
        "| Generation | rate | count / n |",
        "|---|---|---|",
    ]
    for key, title in (
        ("correct_refusal_unanswerable", "Refused unanswerable (hallucination guard)"),
        ("false_refusal_answerable", "Refused answerable (false refusals)"),
        ("faithful", "Faithful (judge, answered items)"),
        ("relevant", "Relevant (judge, answered items)"),
        ("correct_answerable", "Correct (judge; refusals count as not correct)"),
        ("near_miss_pairs_both_correct", "Near-miss pairs with both answers correct"),
    ):
        v = g[key]
        lines.append(f"| {title} | {pct(v['rate'])} | {v['count']} / {v['n']} |")
    lines += [
        "",
        f"Judge errors: {g['judge_errors']}. "
        f"Hallucinated on unanswerable: {g['hallucinated_on_unanswerable'] or 'none'}. "
        f"Refused answerable: {g['refused_answerable'] or 'none'}.",
        "",
    ]
    section = "\n".join(lines)
    heading = lines[0]
    text = EVAL_RESULTS_MD.read_text(encoding="utf-8")
    if heading in text:
        before, _, after = text.partition(heading)
        rest = after.split("\n## ", 1)
        text = before + section + ("\n## " + rest[1] if len(rest) > 1 else "")
    else:
        marker = "\n## Measurement notes"
        text = text.replace(marker, "\n" + section + marker, 1) if marker in text else text + "\n" + section
    EVAL_RESULTS_MD.write_text(text, encoding="utf-8")


def previous_result(mode: str, exclude: Path) -> dict[str, Any] | None:
    files = sorted(p for p in RESULTS_DIR.glob(f"*_{mode}.json") if p != exclude)
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def print_comparison(current: dict[str, Any], previous: dict[str, Any] | None) -> None:
    def rows(agg: dict[str, Any]) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for group, m in agg["retrieval"].items():
            for k in ("recall@6", "recall@10", "mrr", "ndcg@10"):
                out[f"{group} {k}"] = m[k]
        for k, v in agg.get("generation", {}).items():
            if isinstance(v, dict):
                out[k] = v["rate"]
        return out

    cur = rows(current["aggregate"])
    prev = rows(previous["aggregate"]) if previous else {}
    label = f"previous ({previous['meta']['run_id']})" if previous else "previous (none)"
    print(f"\n{'metric':45s} {label:>30s} {'current':>10s} {'delta':>8s}")
    for k, v in cur.items():
        p = prev.get(k)
        delta = f"{v - p:+.3f}" if v is not None and p is not None else ""
        print(f"{k:45s} {_fmt(p):>30s} {_fmt(v):>10s} {delta:>8s}")
    if previous and previous["meta"]["golden_hash"] != current["meta"]["golden_hash"]:
        print("WARNING: golden set changed since the previous run; deltas are not comparable.")


def read_partial(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[0])["meta"], [json.loads(line) for line in lines[1:] if line.strip()]


async def run(
    args: argparse.Namespace,
    golden: list[dict[str, Any]],
    resumed: tuple[dict[str, Any], list[dict[str, Any]]] | None,
) -> int:
    settings = get_settings()
    resume_records: list[dict[str, Any]] = []
    if resumed:
        meta, resume_records = resumed
        args.subset, args.retrieval_only, args.baseline = (
            meta["subset"],
            meta["retrieval_only"],
            meta["baseline"],
        )
        if meta["golden_hash"] != golden_hash():
            raise SystemExit("golden set changed since this partial run started; start a new run")
        partial = Path(args.resume)
        run_id = meta["run_id"]
    if args.baseline and (args.subset or args.retrieval_only):
        raise SystemExit("--baseline requires a full run with judging (no --subset, no --retrieval-only)")
    mode = mode_name(args.subset, args.retrieval_only)
    items = select_subset(golden, args.subset) if args.subset else golden
    delay_s = (args.delay_ms if args.delay_ms is not None else settings.eval_request_delay_ms) / 1000
    if not args.resume:
        run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{mode}"
        partial = RESULTS_DIR / f"{run_id}.partial.jsonl"
    done = {r["id"] for r in resume_records}
    todo = [i for i in items if i["id"] not in done]
    calls = 0 if args.retrieval_only else len(todo) + sum(i["type"] != "unanswerable" for i in todo)
    print(
        f"run {run_id}: {len(items)} items ({len(todo)} to do), up to {calls} LLM calls, "
        f"about {calls * delay_s / 60:.0f} min at {delay_s:.0f}s pacing"
    )

    judge_llm = None
    if not args.retrieval_only:
        judge_settings = settings.model_copy(
            update={"llm_max_completion_tokens": settings.eval_judge_max_completion_tokens}
        )
        judge_llm = OpenAICompatibleLLM(judge_settings, settings.eval_judge_tier)

    app = create_app(settings)
    records = list(resume_records)
    started = time.time()
    stopped: str | None = None
    async with app.router.lifespan_context(app):
        pool = app.state.pool
        async with pool.acquire() as conn:
            await resolve_gold_uuids(conn, items)
            corpus_chunks = await conn.fetchval("SELECT count(*) FROM chunks")
        meta = {
            "run_id": run_id,
            "mode": mode,
            "subset": args.subset,
            "retrieval_only": args.retrieval_only,
            "baseline": args.baseline,
            "is_baseline_eligible": mode == "full",
            "n_items": len(items),
            "item_ids": [i["id"] for i in items],
            "golden_hash": golden_hash(),
            "corpus_chunks": corpus_chunks,
            "git_commit": git_commit(),
            "llm_tier": settings.llm_tier,
            "prompt_version": PROMPT_VERSION,
            "judge_tier": None if args.retrieval_only else settings.eval_judge_tier,
            "judge_model": judge_llm.model_id if judge_llm else None,
            "judge_prompt_version": None if args.retrieval_only else JUDGE_PROMPT_VERSION,
            "top_k": settings.retrieval_top_k,
            "retrieve_k": RETRIEVE_K,
            "delay_ms": int(delay_s * 1000),
            "started_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        RESULTS_DIR.mkdir(exist_ok=True)
        if not args.resume:
            partial.write_text(json.dumps({"meta": meta}) + "\n", encoding="utf-8")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://eval", timeout=180) as client:
            for n, item in enumerate(todo, 1):
                try:
                    record = await evaluate_item(item, client, pool, app.state, judge_llm, settings, delay_s)
                except HarnessStopped as exc:
                    stopped = str(exc)
                    break
                records.append(record)
                with partial.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                status = (
                    ""
                    if args.retrieval_only
                    else (
                        " refused"
                        if record.get("refused")
                        else f" judge={'error' if record.get('judge_error') else 'ok'}"
                    )
                )
                print(f"  [{n}/{len(todo)}] {item['id']} {item['type']}{status}", flush=True)
    if judge_llm:
        await judge_llm.aclose()

    if stopped:
        print(f"\nSTOPPED: {stopped}\n{len(records)}/{len(items)} items saved in {partial}")
        print(f"Resume with: uv run python eval/run_eval.py --resume {partial.relative_to(ROOT)}")
        return 2

    meta["generator_model"] = next((r["model"] for r in records if r.get("model")), None)
    meta["finished_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
    meta["elapsed_min"] = round((time.time() - started) / 60, 1)
    result = {"meta": meta, "aggregate": aggregate(records), "records": records}
    out = RESULTS_DIR / f"{run_id}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    partial.unlink()
    eligible = meta["is_baseline_eligible"]
    print(f"\nresults: {out.relative_to(ROOT)} (mode: {mode}; baseline-eligible: {eligible})")
    print_comparison(result, previous_result(mode, out))
    if args.baseline:
        BASELINES_DIR.mkdir(exist_ok=True)
        slug = args.baseline.lower().replace(" ", "-")
        baseline_file = BASELINES_DIR / f"{slug}.json"
        baseline_file.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
        write_baseline_section(args.baseline, result, baseline_file)
        print(f"baseline '{args.baseline}' recorded in EVAL_RESULTS.md and {baseline_file.relative_to(ROOT)}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--subset", type=int, choices=sorted(SUBSET_ALLOCATION), help="fixed stratified sample"
    )
    parser.add_argument("--retrieval-only", action="store_true", help="retrieval metrics only; no LLM calls")
    parser.add_argument("--baseline", metavar="LABEL", help='record a full run as a baseline, e.g. "Phase 2"')
    parser.add_argument("--delay-ms", type=int, help="override EVAL_REQUEST_DELAY_MS")
    parser.add_argument("--resume", metavar="PARTIAL", help="continue a stopped run from its .partial.jsonl")
    args = parser.parse_args()
    resumed = read_partial(Path(args.resume)) if args.resume else None
    sys.exit(asyncio.run(run(args, load_golden(), resumed)))


if __name__ == "__main__":
    main()
