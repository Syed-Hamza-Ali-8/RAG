# Evaluation Results

Every number here is produced by a script in this repo.

## Phase 1 — Baseline latency

**PENDING (prompt `answer-v2`).** Not yet measured. The run started 2026-10-21 19:20 UTC was
stopped after 27 minutes with only 2 of 20 queries answered: Groq returned HTTP 429 on almost
every request and backoff could not recover. Re-run with
`uv run python scripts/measure_latency.py` once the Groq quota has reset. The script overwrites
this section and records the prompt version read from `query_log.prompt_version`.

## Superseded — Phase 1 baseline latency (prompt answer-v1)

**Superseded and not comparable with any answer-v2 figures.** Measured under prompt `answer-v1`
with the original citation parser, which accepted only `[S1]` markers. That parser refused valid
answers that the model cited as `【S1】`. One of the 2 refusals below ("When is the ISO 27001
recertification audit?") was that parser bug, not a real refusal. `query_log` had no
`prompt_version` column when these rows were written. Kept for the record only.

Measured 2026-10-21 18:53 UTC by `uv run python scripts/measure_latency.py` from `query_log` rows written by this run (ids > 89).

- Queries: 20 (20 questions x 1 round(s), 1 warm-up excluded), 20000 ms delay between requests (EVAL_REQUEST_DELAY_MS) for free-tier rate limits
- Tier: `small`; model(s): `openai/gpt-oss-20b`
- Retrieval: vector-only, top_k=6; prompt `answer-v1`
- Refused (zero valid citations): 2/20 (not a quality metric; see Phase 2)
- Requests that hit a 429 retry: 0/20
- Environment: in-process ASGI on WSL2, repo on /mnt/d, Postgres in Docker Desktop

| Metric | p50 (ms) | p95 (ms) | mean (ms) |
|---|---|---|---|
| End-to-end (total_ms) | 815 | 1397 | 902 |
| Retrieval (embed + vector search) | 26 | 81 | 39 |
| LLM call | 770 | 1375 | 863 |

## Known baseline weaknesses

### Single-sentence facts inside large merged chunks

Vector-only retrieval misses single-sentence facts inside large merged chunks.
Measured: the on-call allowance section scores 0.80 against its question when
embedded alone, 0.59 when merged into a 333-token chunk, ranking 27th of 133.
Phase 5 hybrid retrieval (keyword + graph) targets this class of miss.

Reproduce the merged-chunk score and rank with:
`uv run python scripts/diagnose_refusals.py --tenant acme --question "What is the on-call allowance per week?" --needle "PKR 15,000"`
(0.5916, rank 27 of 133, marked MISSED; top-6 cutoff 0.6293). The 0.80 figure (0.8026) came from
embedding the "Allowance and Time Off" section on its own, with the same heading prefix, in a
one-off check on 2026-10-22. That check is not yet a script in this repo.
