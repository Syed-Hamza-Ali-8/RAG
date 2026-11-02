"""Phase 5 M2 feasibility probe: extract the pre-registered 54-chunk subset (EVAL_RESULTS.md, M2 probe).

    uv run python eval/graph_probe.py --extract   # resumable; stops before crossing the daily budget
    uv run python eval/graph_probe.py --extract --all  # the full corpus (after the probe's rule said so)
    uv run python eval/graph_probe.py --report    # extraction outcomes, cost and time per document

Then measure with the harness (no LLM calls):
    RETRIEVAL_MODE=hybrid_graph uv run python eval/run_eval.py --retrieval-only \
        --compare-to eval/phase5/m1_hybrid.json

Extraction uses the .env extraction tier (EXTRACTION_TIER) and logs every attempt in graph_extraction (model,
prompt version, tokens, time, outcome). A chunk with an 'ok' row for the current prompt version is skipped. A
provider error stops the run rather than being repeated on every remaining chunk.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from gateway.config import Settings, get_settings
from gateway.db import create_pool
from gateway.graph.extract import EXTRACT_PROMPT_VERSION, extract_chunk
from gateway.llm.provider import OpenAICompatibleLLM
from gateway.routing.policy import price_for, shadow_cost
from run_eval import BUDGET_MARGIN, require_stack, tokens_used_24h

SUBSET = Path(__file__).resolve().parent / "phase5" / "graph_probe_subset.json"
# EVAL_RESULTS.md, M2 probe deviation: a non-ok outcome among the setup's first 5 attempts (across runs)
# stops extraction; a failed chunk gets one retry, never a third draw.
FIRST_N_STRICT = 5
MAX_ATTEMPTS = 2
EST_TOKENS_PER_CHUNK = 2000  # pre-registered estimate (1.5-2k); the live check uses logged tokens


@dataclass
class DocStats:
    attempted: int = 0
    ok: int = 0
    llm_ms: int = 0
    cost: Decimal = Decimal(0)
    entities: int = 0
    relations: int = 0


async def all_chunks(settings: Settings) -> list[dict[str, str]]:
    """Every chunk of the seeded corpus, in a fixed order (full-corpus extraction after the probe's rule)."""
    pool = await create_pool(settings.database_dsn)
    try:
        rows = await pool.fetch(
            "SELECT t.slug AS tenant, d.slug || '#' || c.ordinal AS chunk FROM chunks c "
            "JOIN documents d ON d.id = c.document_id JOIN tenants t ON t.id = c.tenant_id "
            "ORDER BY t.slug, d.slug, c.ordinal"
        )
    finally:
        await pool.close()
    return [{"tenant": r["tenant"], "chunk": r["chunk"]} for r in rows]


async def extract(settings: Settings, everything: bool = False) -> int:
    rows = await all_chunks(settings) if everything else json.loads(SUBSET.read_text(encoding="utf-8"))
    llm = OpenAICompatibleLLM(
        settings.model_copy(
            update={
                "llm_max_completion_tokens": settings.extraction_max_completion_tokens,
                "llm_reasoning_effort": settings.extraction_reasoning_effort,
            }
        ),
        settings.extraction_tier,
    )
    pool = await create_pool(settings.database_dsn)
    done = failed = 0
    try:
        for n, row in enumerate(rows, 1):
            slug, ordinal = row["chunk"].rsplit("#", 1)
            async with pool.acquire() as conn:
                c = await conn.fetchrow(
                    "SELECT c.id, c.tenant_id, c.heading_path, c.content FROM chunks c "
                    "JOIN documents d ON d.id = c.document_id JOIN tenants t ON t.id = c.tenant_id "
                    "WHERE t.slug = $1 AND d.slug = $2 AND c.ordinal = $3",
                    row["tenant"],
                    slug,
                    int(ordinal),
                )
                if c is None:
                    raise SystemExit(f"{row['tenant']}/{row['chunk']} is not in the corpus")
                ok, attempts = await conn.fetchrow(
                    "SELECT bool_or(outcome = 'ok'), count(*) FROM graph_extraction "
                    "WHERE chunk_id = $1 AND prompt_version = $2",
                    c["id"],
                    EXTRACT_PROMPT_VERSION,
                )
                if ok or attempts >= MAX_ATTEMPTS:
                    continue
                used = await tokens_used_24h(conn, llm.model_id)
            if used + EST_TOKENS_PER_CHUNK * BUDGET_MARGIN > settings.llm_daily_token_limit:
                print(f"STOPPED (budget): {llm.model_id} at {used:,} tokens; run --extract again later")
                return 2
            outcome = await extract_chunk(
                pool,
                llm,
                tenant_id=c["tenant_id"],
                chunk_id=c["id"],
                heading_path=c["heading_path"],
                content=c["content"],
            )
            done += outcome == "ok"
            failed += outcome != "ok"
            print(f"  [{n}/{len(rows)}] {row['tenant']}/{row['chunk']}: {outcome}", flush=True)
            async with pool.acquire() as conn:
                setup_attempts = await conn.fetchval(
                    "SELECT count(*) FROM graph_extraction WHERE prompt_version = $1", EXTRACT_PROMPT_VERSION
                )
            if outcome != "ok" and setup_attempts <= FIRST_N_STRICT:
                print(f"STOPPED: {outcome} within the first {FIRST_N_STRICT} attempts (stop rule)")
                return 2
            if outcome == "error":
                print("STOPPED: provider error (see graph_extraction.error); not repeating it on every chunk")
                return 2
            await asyncio.sleep(settings.eval_request_delay_ms / 1000)
    finally:
        await llm.aclose()
        await pool.close()
    print(f"extraction pass done: {done} ok, {failed} failed this run")
    return 0


async def report(settings: Settings) -> int:
    pool = await create_pool(settings.database_dsn)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.slug AS tenant, d.slug AS doc, g.outcome, g.model_used, g.prompt_tokens,
                       g.completion_tokens, g.llm_ms, g.entities, g.relations
                FROM graph_extraction g JOIN chunks c ON c.id = g.chunk_id
                JOIN documents d ON d.id = c.document_id JOIN tenants t ON t.id = g.tenant_id
                WHERE g.prompt_version = $1 ORDER BY 1, 2
                """,
                EXTRACT_PROMPT_VERSION,
            )
            graph = await conn.fetchrow(
                "SELECT (SELECT count(*) FROM entities) e, (SELECT count(*) FROM relations) r"
            )
    finally:
        await pool.close()
    if not rows:
        print("no extraction attempts logged")
        return 1
    price = price_for(settings, settings.extraction_tier)
    per_doc: dict[str, DocStats] = {}
    for r in rows:
        d = per_doc.setdefault(f"{r['tenant']}/{r['doc']}", DocStats())
        d.attempted += 1
        d.ok += r["outcome"] == "ok"
        d.llm_ms += r["llm_ms"] or 0
        d.cost += shadow_cost(price, r["prompt_tokens"], r["completion_tokens"]) or Decimal(0)
        d.entities += r["entities"] or 0
        d.relations += r["relations"] or 0
    print(f"model {rows[0]['model_used']}, prompt {EXTRACT_PROMPT_VERSION}")
    print(f"graph: {graph['e']} entities, {graph['r']} relations")
    print("| document | chunks attempted | ok | LLM time | shadow cost (USD) | entities | relations |")
    print("|---|---|---|---|---|---|---|")
    for doc, d in sorted(per_doc.items()):
        print(
            f"| {doc} | {d.attempted} | {d.ok} | {d.llm_ms / 1000:.1f} s | {d.cost} "
            f"| {d.entities} | {d.relations} |"
        )
    outcomes: dict[str, int] = {}
    for r in rows:
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    tokens = sum((r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0) for r in rows)
    print(f"outcomes {outcomes}; total tokens {tokens:,}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--extract", action="store_true")
    g.add_argument("--report", action="store_true")
    ap.add_argument("--all", action="store_true", help="with --extract: the whole corpus")
    ap.add_argument("--force-containers", action="store_true")
    a = ap.parse_args()
    settings = get_settings()
    if a.report:
        sys.exit(asyncio.run(report(settings)))
    require_stack(strict=True, force_containers=a.force_containers)
    sys.exit(asyncio.run(extract(settings, everything=a.all)))


if __name__ == "__main__":
    main()
