"""Phase 1 latency baseline: run a fixed question set through POST /v1/query (in-process,
real DB, real embedder, configured LLM tier), then compute percentiles from query_log rows
written by this run and record them in EVAL_RESULTS.md.

This measures latency only. Answer quality is Phase 2's eval harness (eval/run_eval.py).
"""

import argparse
import asyncio
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from gateway.config import get_settings
from gateway.db import create_pool
from gateway.llm.prompts import PROMPT_VERSION
from gateway.main import create_app

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "EVAL_RESULTS.md"
SECTION = "## Phase 1 — Baseline latency"

QUESTIONS: list[tuple[str, str]] = [
    ("acme", "How many days of paid annual leave do full-time employees get?"),
    ("acme", "Who signed the Halvorsen Logistics master services agreement for Acme?"),
    ("acme", "What is the recovery time objective for Atlas?"),
    ("acme", "What caused the Atlas outage in March 2026?"),
    ("acme", "What is the on-call allowance per week?"),
    ("acme", "When is the ISO 27001 recertification audit?"),
    ("acme", "What approval is needed for an expense above USD 5,000?"),
    ("acme", "What is the minimum salary for a Manager in Karachi?"),
    ("acme", "How long is paternity leave?"),
    ("acme", "Which region hosts Brightwater Health patient data?"),
    ("globex", "How many days of annual leave do Globex employees get?"),
    ("globex", "What is the Tessera Cloud monthly fee?"),
    ("globex", "When is the Marlowe Retail audit report due?"),
    ("globex", "What caused the Ledger Vault outage?"),
    ("globex", "How long are database backups kept?"),
    ("globex", "What bonus do staff get for passing an ACCA paper?"),
    ("globex", "Who chairs the performance moderation committee?"),
    ("globex", "What is the gifts limit in the code of conduct?"),
    ("globex", "When does the Pemberton Construction NDA expire?"),
    ("globex", "What is the per diem in the UAE?"),
]


def pct(values: list[int], p: float) -> int:
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1))))
    return ordered[k]


async def run(delay_s: float, rounds: int) -> None:
    settings = get_settings()
    pool = await create_pool(settings.database_dsn)
    app = create_app(settings)
    failures: list[str] = []
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://bench", timeout=180) as client:
            # Warm-up (excluded): first ONNX inference and connection setup.
            await client.post("/v1/query", json={"tenant": "acme", "question": "warm up"})
            async with pool.acquire() as conn:
                start_id = await conn.fetchval("SELECT coalesce(max(id), 0) FROM query_log")
            for _ in range(rounds):
                for tenant, question in QUESTIONS:
                    r = await client.post("/v1/query", json={"tenant": tenant, "question": question})
                    if r.status_code != 200:
                        failures.append(f"{r.status_code} {question}: {r.text[:200]}")
                    await asyncio.sleep(delay_s)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT total_ms, retrieval_ms, llm_ms, refused, model_used FROM query_log "
            "WHERE id > $1 ORDER BY id",
            start_id,
        )
    await pool.close()
    if failures:
        sys.exit("requests failed; no measurement recorded:\n" + "\n".join(failures))
    if not rows:
        sys.exit("no query_log rows written")

    total = [r["total_ms"] for r in rows]
    retrieval = [r["retrieval_ms"] for r in rows]
    llm = [r["llm_ms"] for r in rows if r["llm_ms"] is not None]
    refused = sum(r["refused"] for r in rows)
    models = sorted({r["model_used"] for r in rows if r["model_used"]})
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    table = [
        "| Metric | p50 (ms) | p95 (ms) | mean (ms) |",
        "|---|---|---|---|",
        f"| End-to-end (total_ms) | {pct(total, 50)} | {pct(total, 95)} | {statistics.mean(total):.0f} |",
        f"| Retrieval (embed + vector search) | {pct(retrieval, 50)} | {pct(retrieval, 95)} "
        f"| {statistics.mean(retrieval):.0f} |",
        f"| LLM call | {pct(llm, 50)} | {pct(llm, 95)} | {statistics.mean(llm):.0f} |",
    ]
    section = "\n".join(
        [
            SECTION,
            "",
            f"Measured {stamp} by `uv run python scripts/measure_latency.py` from `query_log` rows "
            f"written by this run (ids > {start_id}).",
            "",
            f"- Queries: {len(rows)} ({len(QUESTIONS)} questions x {rounds} round(s), 1 warm-up excluded), "
            f"{delay_s:.1f}s delay between requests for free-tier rate limits",
            f"- Tier: `{settings.llm_tier}`; model(s): {', '.join(f'`{m}`' for m in models)}",
            f"- Retrieval: vector-only, top_k={settings.retrieval_top_k}; prompt `{PROMPT_VERSION}`",
            f"- Refused (zero valid citations): {refused}/{len(rows)} (not a quality metric; see Phase 2)",
            "- Environment: in-process ASGI on WSL2, repo on /mnt/d, Postgres in Docker Desktop",
            "",
            *table,
            "",
        ]
    )
    header = "# Evaluation Results\n\nEvery number here is produced by a script in this repo.\n\n"
    text = RESULTS.read_text(encoding="utf-8") if RESULTS.exists() else header
    if SECTION in text:
        before, _, after = text.partition(SECTION)
        rest = after.split("\n## ", 1)
        text = before + section + ("\n## " + rest[1] if len(rest) > 1 else "")
    else:
        text = text.rstrip("\n") + "\n\n" + section
    RESULTS.write_text(text, encoding="utf-8")
    print(section)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay-s", type=float, default=2.0)
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(run(args.delay_s, args.rounds))


if __name__ == "__main__":
    main()
