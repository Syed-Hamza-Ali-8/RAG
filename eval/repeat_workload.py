"""Phase 4 gate, Run B: cache hit rate on a realistic repeat workload (EVAL_RESULTS.md, Phase 4 gate plan).

    uv run python eval/repeat_workload.py --build              # write eval/repeat_workload.jsonl
    uv run python eval/repeat_workload.py --run RUN_A.json     # replay; no LLM calls

Workload: the 100 golden items with a Zipf-shaped repeat distribution, a few asked many times and most asked
once (item at popularity rank r is asked ceil(40 / r) times), in a fixed shuffled order, each request made by
the item's own seeded user with the exact question text. Variants and paraphrases were measured separately
in the cache sweep.

Run B makes no LLM calls: on a miss it replays the item's real answer from Run A (the full Phase 4 run, cache
on, single pass), so what a miss would cost is that item's Run A shadow cost and model latency. A refused or
truncated item stays refused or truncated, so it is never stored. Cache cleared at the start, threshold and
bypass list from .env.

Prediction (exact once Run A is known): every repeat of a cacheable item hits (the first ask stores it, TTL
24 h outlives the run); bypassed, refused and truncated items never hit. hits = sum over cacheable items of
(asks - 1).
"""

import argparse
import asyncio
import json
import math
import random
import statistics
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from openai.types.chat import ChatCompletionMessageParam

from gateway.cache.semantic import CacheConfig
from gateway.config import Settings, get_settings
from gateway.deps import auth_for_email
from gateway.errors import TruncatedCompletion
from gateway.llm.provider import Completion
from gateway.main import create_app
from gateway.security.tokens import issue_token
from run_eval import RESULTS_DIR, load_golden, require_stack

WORKLOAD = Path(__file__).resolve().parent / "repeat_workload.jsonl"
SEED = "gateway-repeat-workload-v1"
TOP_ASKS = 40


def build() -> list[dict[str, Any]]:
    golden = load_golden()
    rng = random.Random(SEED)
    ranked = [g["id"] for g in golden]
    rng.shuffle(ranked)  # popularity rank is random, not tied to item type
    asks = {iid: math.ceil(TOP_ASKS / r) for r, iid in enumerate(ranked, 1)}
    requests = [iid for iid, n in asks.items() for _ in range(n)]
    rng.shuffle(requests)
    rows = [{"n": n, "id": iid, "asks": asks[iid]} for n, iid in enumerate(requests, 1)]
    WORKLOAD.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    once = sum(1 for n in asks.values() if n == 1)
    print(
        f"{len(rows)} requests over {len(asks)} items; {once} asked once; "
        f"top item asked {max(asks.values())}x"
    )
    return rows


def load_workload() -> list[dict[str, Any]]:
    return [json.loads(x) for x in WORKLOAD.read_text(encoding="utf-8").splitlines() if x.strip()]


class ReplayLLM:
    """Replays each item's real Run A generation; truncations stay truncations."""

    tier = "small"

    def __init__(self, recorded: dict[str, dict[str, Any]], model_id: str) -> None:
        self.recorded, self.model_id, self.current = recorded, model_id, ""

    async def complete(self, messages: list[ChatCompletionMessageParam]) -> Completion:
        rec = self.recorded[self.current]
        if rec["outcome"] == "truncated":
            raise TruncatedCompletion(
                self.model_id, rec["prompt_tokens"], rec["completion_tokens"], rec["answer_raw"] or ""
            )
        return Completion(rec["answer_raw"] or "", self.model_id, None, None)


async def _recorded(settings: Settings, run_a: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each item's Run A query_log row: real answer, outcome, tokens, cost, model latency."""
    from gateway.db import create_pool

    pool = await create_pool(settings.database_dsn)
    try:
        async with pool.acquire() as conn:
            out = {}
            for r in run_a["records"]:
                row = await conn.fetchrow(
                    "SELECT answer_raw, outcome, prompt_tokens, completion_tokens, est_cost_usd, llm_ms, "
                    "cache_hit "
                    "FROM query_log WHERE id = $1",
                    r["query_log_id"],
                )
                out[r["id"]] = dict(row)
    finally:
        await pool.close()
    return out


async def run(settings: Settings, run_a: dict[str, Any], run_a_name: str) -> int:
    if run_a["meta"].get("mode") != "full" or not run_a["meta"].get("cache_enabled"):
        raise SystemExit("Run B replays a full Phase 4 run made with the cache on")
    recorded = await _recorded(settings, run_a)
    golden = {g["id"]: g for g in load_golden()}
    workload = load_workload()
    cfg = CacheConfig.from_patterns(
        settings.cache_similarity_threshold, settings.cache_ttl_hours, settings.cache_bypass_patterns
    )
    cacheable = {
        iid
        for iid, rec in recorded.items()
        if rec["outcome"] == "answered" and not cfg.bypassed(golden[iid]["question"])
    }
    asks: dict[str, int] = {}
    for w in workload:
        asks[w["id"]] = asks.get(w["id"], 0) + 1
    predicted = sum(n - 1 for iid, n in asks.items() if iid in cacheable)
    llm = ReplayLLM(recorded, run_a["meta"].get("generator_model") or "replay")
    app = create_app(settings.model_copy(update={"cache_enabled": True, "routing_enabled": False}), llm=llm)  # type: ignore[arg-type]
    rows = []
    async with app.router.lifespan_context(app):
        pool = app.state.pool
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM semantic_cache")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://b", timeout=60
        ) as c:
            for w in workload:
                g = golden[w["id"]]
                async with pool.acquire() as conn:
                    auth = await auth_for_email(conn, g["tenant"], g["as_user"])
                token = issue_token(settings, user_id=auth.user_id, tenant_id=auth.tenant_id)
                llm.current = w["id"]
                started = time.perf_counter()
                r = await c.post(
                    "/v1/query",
                    json={"question": g["question"]},
                    headers={"Authorization": f"Bearer {token}"},
                )
                wall = round((time.perf_counter() - started) * 1000)
                if r.status_code not in (200, 502):
                    raise SystemExit(f"request {w['n']} ({w['id']}): {r.status_code} {r.text[:200]}")
                async with pool.acquire() as conn:
                    q = await conn.fetchrow(
                        "SELECT cache_hit, total_ms, cache_lookup_ms FROM query_log WHERE tenant_id = $1 "
                        "ORDER BY id DESC LIMIT 1",
                        auth.tenant_id,
                    )
                rows.append(
                    {
                        **w,
                        "cache_hit": bool(q["cache_hit"]),
                        "total_ms": q["total_ms"],
                        "wall_ms": wall,
                        "lookup_ms": q["cache_lookup_ms"],
                    }
                )
    hits = [r for r in rows if r["cache_hit"]]
    misses = [r for r in rows if not r["cache_hit"]]
    cost = {iid: rec["est_cost_usd"] or Decimal(0) for iid, rec in recorded.items()}
    without = sum((cost[r["id"]] for r in rows), Decimal(0))
    saved = sum((cost[r["id"]] for r in hits), Decimal(0))
    llm_ms = [rec["llm_ms"] for rec in recorded.values() if rec["llm_ms"]]
    result = {
        "meta": {
            "ran_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "run_a": run_a_name,
            "threshold": settings.cache_similarity_threshold,
            "requests": len(rows),
            "items": len(asks),
            "cacheable_items": len(cacheable),
            "predicted_hits": predicted,
        },
        "summary": {
            "hits": len(hits),
            "hit_rate": round(len(hits) / len(rows), 4),
            "p50_hit_ms": statistics.median(r["total_ms"] for r in hits) if hits else None,
            "p50_miss_ms_excl_model": statistics.median(r["total_ms"] for r in misses) if misses else None,
            "run_a_model_p50_ms": statistics.median(llm_ms) if llm_ms else None,
            "shadow_cost_without_cache_usd": str(without),
            "shadow_cost_with_cache_usd": str(without - saved),
            "shadow_cost_saved_usd": str(saved),
            "saved_share": round(float(saved / without), 4) if without else None,
        },
        "requests": rows,
    }
    out = RESULTS_DIR / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_repeat_workload.json"
    out.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print(json.dumps(result["meta"], indent=1))
    print(json.dumps(result["summary"], indent=1))
    print(
        "prediction:",
        "HELD" if len(hits) == predicted else f"MISSED ({len(hits)} hits vs {predicted} predicted)",
    )
    print(f"results: {out}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--build", action="store_true")
    g.add_argument("--run", type=Path, metavar="RUN_A_JSON")
    ap.add_argument("--force-containers", action="store_true")
    a = ap.parse_args()
    if a.build:
        build()
        sys.exit(0)
    require_stack(strict=True, force_containers=a.force_containers)
    run_a = json.loads(a.run.read_text(encoding="utf-8"))
    sys.exit(asyncio.run(run(get_settings(), run_a, a.run.name)))


if __name__ == "__main__":
    main()
