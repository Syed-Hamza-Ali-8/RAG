# Evaluation Results

Every number here is produced by a script in this repo.

## Phase 1 — Baseline latency

Measured 2026-10-21 15:55 UTC by `uv run python scripts/measure_latency.py` from `query_log` rows written by this run (ids > 2).

- Queries: 20 (20 questions x 1 round(s), 1 warm-up excluded), 2.0s delay between requests for free-tier rate limits
- Tier: `small`; model(s): `openai/gpt-oss-20b`
- Retrieval: vector-only, top_k=6; prompt `answer-v1`
- Refused (zero valid citations): 0/20 (not a quality metric; see Phase 2)
- Environment: in-process ASGI on WSL2, repo on /mnt/d, Postgres in Docker Desktop

| Metric | p50 (ms) | p95 (ms) | mean (ms) |
|---|---|---|---|
| End-to-end (total_ms) | 785 | 2476 | 1196 |
| Retrieval (embed + vector search) | 27 | 48 | 32 |
| LLM call | 766 | 2428 | 1165 |
