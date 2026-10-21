"""Phase 1 latency baseline: run a fixed question set through POST /v1/query (in-process,
real DB, real embedder, configured LLM tier), then compute percentiles from query_log rows
written by this run and record them in EVAL_RESULTS.md.

This measures latency only. Answer quality is Phase 2's eval harness (eval/run_eval.py).
"""

import argparse
import asyncio
import logging
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
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


class RetryCounter(logging.Handler):
    """Counts 429/5xx retry warnings from gateway.llm.retry. Requests run sequentially, so the
    count delta across one request is that request's retry count."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.count += 1


def pct(values: list[int], p: float) -> int:
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1))))
    return ordered[k]


def stats_table(rows: list[asyncpg.Record]) -> list[str]:
    total = [r["total_ms"] for r in rows]
    retrieval = [r["retrieval_ms"] for r in rows]
    llm = [r["llm_ms"] for r in rows if r["llm_ms"] is not None]
    return [
        "| Metric | p50 (ms) | p95 (ms) | mean (ms) |",
        "|---|---|---|---|",
        f"| End-to-end (total_ms) | {pct(total, 50)} | {pct(total, 95)} | {statistics.mean(total):.0f} |",
        f"| Retrieval (embed + vector search) | {pct(retrieval, 50)} | {pct(retrieval, 95)} "
        f"| {statistics.mean(retrieval):.0f} |",
        f"| LLM call | {pct(llm, 50)} | {pct(llm, 95)} | {statistics.mean(llm):.0f} |",
    ]


async def run(delay_ms: int, rounds: int) -> None:
    settings = get_settings()
    delay_s = delay_ms / 1000
    pool = await create_pool(settings.database_dsn)
    app = create_app(settings)
    failures: list[str] = []
    retries_per_request: list[int] = []
    counter = RetryCounter()
    logging.getLogger("gateway.llm.retry").addHandler(counter)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://bench", timeout=180) as client:
            # Warm-up (excluded): first ONNX inference and connection setup.
            await client.post("/v1/query", json={"tenant": "acme", "question": "warm up"})
            async with pool.acquire() as conn:
                start_id = await conn.fetchval("SELECT coalesce(max(id), 0) FROM query_log")
            for _ in range(rounds):
                for tenant, question in QUESTIONS:
                    before = counter.count
                    r = await client.post("/v1/query", json={"tenant": tenant, "question": question})
                    retries_per_request.append(counter.count - before)
                    if r.status_code != 200:
                        failures.append(f"{r.status_code} {question}: {r.text[:200]}")
                    await asyncio.sleep(delay_s)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, total_ms, retrieval_ms, llm_ms, refused, model_used, prompt_version "
            "FROM query_log WHERE id > $1 ORDER BY id",
            start_id,
        )
    await pool.close()
    if failures:
        sys.exit("requests failed; no measurement recorded:\n" + "\n".join(failures))
    if len(rows) != len(retries_per_request):
        sys.exit(f"expected {len(retries_per_request)} query_log rows, found {len(rows)}")

    # Runs under different prompt versions are not comparable; refuse to mix them.
    versions = {r["prompt_version"] for r in rows if r["prompt_version"] is not None}
    if versions != {PROMPT_VERSION}:
        sys.exit(f"query_log prompt_version(s) {sorted(versions)} != current {PROMPT_VERSION!r}")
    asked = [q for _ in range(rounds) for q in QUESTIONS]
    refused_questions = [
        f"  - [{tenant}] {question} (query_log id {row['id']})"
        for row, (tenant, question) in zip(rows, asked, strict=True)
        if row["refused"]
    ]

    clean = [row for row, n in zip(rows, retries_per_request, strict=True) if n == 0]
    retried = len(rows) - len(clean)
    if not clean:
        sys.exit("every request hit a 429 retry; raise --delay-ms and re-run")
    refused = sum(r["refused"] for r in rows)
    models = sorted({r["model_used"] for r in rows if r["model_used"]})
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    if retried == 0:
        tables = [
            "**Baseline — clean: no request hit a 429 retry, so no backoff wait is included.**",
            "",
            *stats_table(rows),
        ]
    else:
        tables = [
            f"**Baseline — excluding retried requests ({len(clean)} of {len(rows)}): "
            "no 429 backoff wait included.**",
            "",
            *stats_table(clean),
            "",
            f"For reference only — all {len(rows)} requests, including {retried} that waited on "
            f"429 backoff ({sum(retries_per_request)} retries). Not a baseline.",
            "",
            *stats_table(rows),
        ]
    section = "\n".join(
        [
            SECTION,
            "",
            f"Measured {stamp} by `uv run python scripts/measure_latency.py` from `query_log` rows "
            f"written by this run (ids > {start_id}).",
            "",
            f"- Queries: {len(rows)} ({len(QUESTIONS)} questions x {rounds} round(s), 1 warm-up excluded), "
            f"{delay_ms} ms delay between requests (EVAL_REQUEST_DELAY_MS) for free-tier rate limits",
            f"- Tier: `{settings.llm_tier}`; model(s): {', '.join(f'`{m}`' for m in models)}",
            f"- **Prompt version: `{PROMPT_VERSION}`** (read from `query_log.prompt_version` for every row)",
            f"- Retrieval: vector-only, top_k={settings.retrieval_top_k}",
            f"- Refused (zero valid citations): {refused}/{len(rows)} (not a quality metric; see Phase 2)",
            *refused_questions,
            f"- Requests that hit a 429 retry: {retried}/{len(rows)}",
            "- Environment: in-process ASGI on WSL2, repo on /mnt/d, Postgres in Docker Desktop",
            "",
            *tables,
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
    parser.add_argument("--delay-ms", type=int, help="default: EVAL_REQUEST_DELAY_MS from .env")
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()
    delay_ms = args.delay_ms if args.delay_ms is not None else get_settings().eval_request_delay_ms
    asyncio.run(run(delay_ms, args.rounds))


if __name__ == "__main__":
    main()
