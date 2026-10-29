"""Phase 4 routing measurement, cache off (EVAL_RESULTS.md, Phase 4 routing pre-registration).

    uv run python eval/routing_sweep.py --record   # large tier: subset + supplement; small tier: supplement
    uv run python eval/routing_sweep.py --judge    # judge every recorded answer not yet judged (resumable)
    uv run python eval/routing_sweep.py --report   # replay the routing policy at each threshold

Small-tier answers for the 25 subset items are the ones recorded for the cache sweep on 2026-10-29
(eval/cache_sweep/recording.json, cache off, answer-v2); their token counts come from the matching
query_log rows and their verdicts from the cache sweep's judging (same question, same answer). Everything
else is recorded here. Routing is then replayed: each item's outcome at a threshold is the judged answer of
the tier its complexity score selects; its cost is that answer's tokens at that tier's list price.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
import httpx

from gateway.config import Settings, get_settings
from gateway.deps import auth_for_email
from gateway.llm.provider import OpenAICompatibleLLM
from gateway.main import create_app
from gateway.retrieval.vector import vector_search
from gateway.routing.classifier import complexity
from gateway.routing.policy import Router, price_for, shadow_cost
from gateway.security.tokens import issue_token
from judge import Source
from run_eval import (
    BUDGET_MARGIN,
    RESULTS_DIR,
    judge_and_log,
    load_golden,
    preflight,
    require_stack,
    select_subset,
    tokens_per_call,
    tokens_used_24h,
)

EVAL_DIR = Path(__file__).resolve().parent
CACHE_RECORDING = EVAL_DIR / "cache_sweep" / "recording.json"
CACHE_VERDICTS = EVAL_DIR / "cache_sweep" / "sweep.verdicts.jsonl"
RECORDING = RESULTS_DIR / "routing_recording.jsonl"
VERDICTS = RESULTS_DIR / "routing_verdicts.jsonl"
SUPPLEMENT = ("q029", "q051", "q058", "q064", "q066", "q106", "q109")
THRESHOLDS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01)


def items() -> list[dict[str, Any]]:
    golden = load_golden()
    by_id = {g["id"]: g for g in golden}
    subset = select_subset(golden, 25)
    return [{**g, "set": "subset"} for g in subset] + [{**by_id[i], "set": "supplement"} for i in SUPPLEMENT]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def append(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


async def _retrieval(
    app: Any, conn: asyncpg.Connection, item: dict[str, Any], top_k: int
) -> tuple[Any, list[Any]]:
    auth = await auth_for_email(conn, item["tenant"], item["as_user"])
    hits = await vector_search(
        conn,
        acl_filter=auth.acl(),
        query_embedding=await app.state.embedder.embed_query(item["question"]),
        top_k=top_k,
    )
    return auth, hits


async def record(settings: Settings) -> int:
    """Record what is missing: large tier for all items, small tier for the supplement, plus the reused
    small-tier subset answers with their query_log tokens. Stops cleanly before crossing a daily cap."""
    RESULTS_DIR.mkdir(exist_ok=True)
    have = {(r["tier"], r["id"]) for r in read_jsonl(RECORDING)}
    work = items()
    cache_rec = json.loads(CACHE_RECORDING.read_text(encoding="utf-8"))["items"]
    for tier in ("small", "large"):
        todo = [
            i for i in work if (tier, i["id"]) not in have and not (tier == "small" and i["set"] == "subset")
        ]
        llm = OpenAICompatibleLLM(settings, tier)
        s = settings.model_copy(update={"llm_tier": tier, "cache_enabled": False, "routing_enabled": False})
        app = create_app(s, llm=llm)
        async with app.router.lifespan_context(app):
            pool = app.state.pool
            if tier == "small":
                await _import_cached_small(pool, app, work, cache_rec, have, settings)
            async with pool.acquire() as conn:
                await preflight(conn, settings.llm_daily_token_limit, {llm.model_id: [("query", len(todo))]})
                per_call = await tokens_per_call(conn, llm.model_id, "query")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://r", timeout=180
            ) as c:
                for n, item in enumerate(todo, 1):
                    async with pool.acquire() as conn:
                        if (
                            await tokens_used_24h(conn, llm.model_id) + per_call * BUDGET_MARGIN
                            > settings.llm_daily_token_limit
                        ):
                            print(
                                f"STOPPED (budget): {tier} tier, {len(todo) - n + 1} items left; "
                                "run --record again later"
                            )
                            await llm.aclose()
                            return 2
                        auth, hits = await _retrieval(app, conn, item, settings.retrieval_top_k)
                    token = issue_token(settings, user_id=auth.user_id, tenant_id=auth.tenant_id)
                    started = time.perf_counter()
                    r = await c.post(
                        "/v1/query",
                        json={"question": item["question"]},
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    truncated = r.status_code == 502 and r.json().get("error") == "llm_truncated"
                    if r.status_code != 200 and not truncated:
                        print(f"STOPPED: {item['id']} {tier}: {r.status_code} {r.text[:200]}")
                        await llm.aclose()
                        return 2
                    async with pool.acquire() as conn:
                        row = await conn.fetchrow(
                            "SELECT outcome, answer_raw, prompt_tokens, completion_tokens, llm_ms, "
                            "model_used "
                            "FROM query_log WHERE tenant_id = $1 ORDER BY id DESC LIMIT 1",
                            auth.tenant_id,
                        )
                    # A truncation is its own recorded outcome (query_log.outcome), counted as not ok.
                    body = {"answer": None} if truncated else r.json()
                    append(
                        RECORDING,
                        {
                            "tier": tier,
                            "id": item["id"],
                            "set": item["set"],
                            "type": item["type"],
                            "answer": body["answer"],
                            **dict(row),
                            "wall_ms": round((time.perf_counter() - started) * 1000),
                            "scores": [h.score for h in hits],
                            "sources": [{"title": h.document_title, "content": h.content} for h in hits],
                        },
                    )
                    print(
                        f"  [{tier} {n}/{len(todo)}] {item['id']} {row['outcome']} "
                        f"{row['completion_tokens']} out-tokens",
                        flush=True,
                    )
                    await asyncio.sleep(settings.eval_request_delay_ms / 1000)
        await llm.aclose()
    print(f"recording complete: {RECORDING}")
    return 0


async def _import_cached_small(
    pool: asyncpg.Pool,
    app: Any,
    work: list[dict[str, Any]],
    cache_rec: dict[str, Any],
    have: set[Any],
    settings: Settings,
) -> None:
    """Reuse the cache sweep's small-tier subset answers; each must match exactly one query_log row."""
    for item in (i for i in work if i["set"] == "subset" and ("small", i["id"]) not in have):
        rec = cache_rec[item["id"]]
        async with pool.acquire() as conn:
            auth, hits = await _retrieval(app, conn, item, settings.retrieval_top_k)
            rows = await conn.fetch(
                # Keyed on the question (audit_log.query_text): refusals share their answer text. The real
                # generation carries token counts; the cache sweep's replayed rows do not.
                "SELECT q.outcome, q.answer_raw, q.prompt_tokens, q.completion_tokens, q.llm_ms, "
                "q.model_used "
                "FROM query_log q JOIN audit_log a ON a.query_log_id = q.id "
                "WHERE q.tenant_id = $1 AND q.purpose = 'query' AND a.query_text = $2 AND q.answer_raw = $3 "
                "AND q.ts BETWEEN '2026-10-29 11:00+00' AND '2026-10-29 11:30+00' AND q.cache_hit IS NULL "
                "AND q.prompt_tokens IS NOT NULL",
                auth.tenant_id,
                item["question"],
                rec["answer_raw"],
            )
        if len(rows) != 1:
            raise SystemExit(
                f"{item['id']}: expected one query_log row for the recorded small answer, got {len(rows)}"
            )
        append(
            RECORDING,
            {
                "tier": "small",
                "id": item["id"],
                "set": "subset",
                "type": item["type"],
                "answer": rec["answer"],
                **dict(rows[0]),
                "wall_ms": None,
                "scores": [h.score for h in hits],
                "sources": rec["sources"],
                "reused_from": "eval/cache_sweep/recording.json",
            },
        )


def judged() -> dict[tuple[str, str], dict[str, Any] | None]:
    """(tier, id) -> verdict. Subset small-tier verdicts come from the cache sweep (same question, answer)."""
    golden = {g["id"]: g for g in load_golden()}
    out: dict[tuple[str, str], dict[str, Any] | None] = {}
    for v in read_jsonl(CACHE_VERDICTS):
        if v["question"] == golden[v["id"]]["question"]:
            out[("small", v["id"])] = v.get("judge")
    for v in read_jsonl(VERDICTS):
        out[(v["tier"], v["id"])] = v.get("judge")
    return out


async def judge(settings: Settings) -> int:
    golden = {g["id"]: g for g in load_golden()}
    done = judged()
    todo = [
        r for r in read_jsonl(RECORDING) if r["outcome"] == "answered" and (r["tier"], r["id"]) not in done
    ]
    print(f"{len(todo)} answers to judge")
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
        if over:
            print("pre-flight: judging does not fit today's judge budget; run again when the window allows")
            await judge_llm.aclose()
            return 1
        for n, r in enumerate(todo, 1):
            g = golden[r["id"]]
            async with pool.acquire() as conn:
                tenant_id = await conn.fetchval("SELECT id FROM tenants WHERE slug = $1", g["tenant"])
            sources = [Source(f"S{k}", s["title"], s["content"]) for k, s in enumerate(r["sources"], 1)]
            out = await judge_and_log(
                pool,
                tenant_id,
                judge_llm,
                g["question"],
                g["expected_answer"],
                sources,
                r["answer"],
                settings.eval_request_delay_ms / 1000,
            )
            append(VERDICTS, {"tier": r["tier"], "id": r["id"], **out})
            print(
                f"  [{n}/{len(todo)}] {r['tier']} {r['id']} "
                f"{out.get('judge', {}).get('correct', out.get('judge_error'))}",
                flush=True,
            )
    await judge_llm.aclose()
    return 0


def ok(rec: dict[str, Any], verdict: dict[str, Any] | None, unanswerable: bool) -> bool:
    if rec["outcome"] == "refused":
        return unanswerable
    return bool(verdict and verdict.get("correct"))


def report(settings: Settings) -> int:
    recs = {(r["tier"], r["id"]): r for r in read_jsonl(RECORDING)}
    verdicts = judged()
    golden = {g["id"]: g for g in load_golden()}
    prices = {t: price_for(settings, t) for t in ("small", "large")}
    for which in ("subset", "supplement"):
        ids = [i["id"] for i in items() if i["set"] == which]
        missing = [(t, i) for i in ids for t in ("small", "large") if (t, i) not in recs]
        unjudged = [
            k
            for k in ((t, i) for i in ids for t in ("small", "large"))
            if k in recs and recs[k]["outcome"] == "answered" and k not in verdicts
        ]
        if missing or unjudged:
            print(f"{which}: incomplete (missing {missing}, unjudged {unjudged})")
            continue
        label = {}
        for i in ids:
            un = golden[i]["type"] == "unanswerable"
            s_ok = ok(recs[("small", i)], verdicts.get(("small", i)), un)
            l_ok = ok(recs[("large", i)], verdicts.get(("large", i)), un)
            label[i] = (s_ok, l_ok)
        needs_large = [i for i, (s_ok, l_ok) in label.items() if not s_ok and l_ok]
        small_better = [i for i, (s_ok, l_ok) in label.items() if s_ok and not l_ok]
        score = {i: complexity(golden[i]["question"], recs[("small", i)]["scores"]).score for i in ids}
        print(
            f"\n## {which} ({len(ids)} items)  small ok {sum(s for s, _ in label.values())}, large ok "
            f"{sum(l_ok for _, l_ok in label.values())}; needs large {needs_large}; "
            f"small better {small_better}"
        )
        print(
            "| threshold | to large | correct | faithful (answered) | refused | shadow cost USD "
            "| LLM p50 ms | needs-large caught |"
        )
        print("|---|---|---|---|---|---|---|---|")
        for t in THRESHOLDS:
            router = Router(t)
            chosen = {i: router.route(score[i]) for i in ids}
            correct = sum(label[i][0] if chosen[i] == "small" else label[i][1] for i in ids)
            answered = [i for i in ids if recs[(chosen[i], i)]["outcome"] == "answered"]
            faithful = sum(bool((verdicts.get((chosen[i], i)) or {}).get("faithful")) for i in answered)
            refused = sum(recs[(chosen[i], i)]["outcome"] == "refused" for i in ids)
            costs = [
                shadow_cost(
                    prices[chosen[i]],
                    recs[(chosen[i], i)]["prompt_tokens"],
                    recs[(chosen[i], i)]["completion_tokens"],
                )
                for i in ids
            ]
            cost = (
                sum((c for c in costs if c is not None), Decimal(0))
                if all(c is not None for c in costs)
                else None
            )
            lat = [recs[(chosen[i], i)]["llm_ms"] for i in ids if recs[(chosen[i], i)]["llm_ms"]]
            caught = sum(chosen[i] == "large" for i in needs_large)
            print(
                f"| {t} | {sum(c == 'large' for c in chosen.values())}/{len(ids)} | {correct}/{len(ids)} | "
                f"{faithful}/{len(answered)} | {refused} | {cost if cost is not None else 'unknown'} | "
                f"{statistics.median(lat) if lat else '-'} | {caught}/{len(needs_large)} |"
            )
        by_type: dict[str, list[float]] = {}
        for i in ids:
            by_type.setdefault(golden[i]["type"], []).append(score[i])
        print(
            "mean complexity score by type: "
            + ", ".join(f"{k} {statistics.mean(v):.3f} (n={len(v)})" for k, v in sorted(by_type.items()))
        )
        tokens = {
            t: [recs[(t, i)]["completion_tokens"] for i in ids if recs[(t, i)]["completion_tokens"]]
            for t in ("small", "large")
        }
        print(
            "completion tokens p50: "
            + ", ".join(f"{t} {statistics.median(v)}" for t, v in tokens.items() if v)
        )
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--record", action="store_true")
    g.add_argument("--judge", action="store_true")
    g.add_argument("--report", action="store_true")
    ap.add_argument("--force-containers", action="store_true")
    a = ap.parse_args()
    settings = get_settings()
    if a.report:
        sys.exit(report(settings))
    require_stack(strict=True, force_containers=a.force_containers)
    sys.exit(asyncio.run(record(settings) if a.record else judge(settings)))


if __name__ == "__main__":
    main()
