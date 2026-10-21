# Evaluation Results

Every number here is produced by a script in this repo.

## Phase 1 — Baseline latency

Measured 2026-10-21 18:53 UTC by `uv run python scripts/measure_latency.py` from `query_log` rows written by this run (ids > 89).

- Queries: 20 (20 questions x 1 round(s), 1 warm-up excluded), 20000 ms delay between requests (EVAL_REQUEST_DELAY_MS) for free-tier rate limits
- Tier: `small`; model(s): `openai/gpt-oss-20b`
- Retrieval: vector-only, top_k=6; prompt `answer-v1`
- Refused (zero valid citations): 2/20 (not a quality metric; see Phase 2)
- Requests that hit a 429 retry: 0/20
- Environment: in-process ASGI on WSL2, repo on /mnt/d, Postgres in Docker Desktop

**Baseline — clean: no request hit a 429 retry, so no backoff wait is included.**

| Metric | p50 (ms) | p95 (ms) | mean (ms) |
|---|---|---|---|
| End-to-end (total_ms) | 815 | 1397 | 902 |
| Retrieval (embed + vector search) | 26 | 81 | 39 |
| LLM call | 770 | 1375 | 863 |
