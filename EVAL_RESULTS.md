# Evaluation Results

Every number here is produced by a script in this repo.

## Phase 1 — Baseline latency

Measured 2026-10-23 11:11 UTC by `uv run python scripts/measure_latency.py` from `query_log` rows written by this run (ids > 145).

- Queries: 20 (20 questions x 1 round(s), 1 warm-up excluded), 30000 ms delay between requests (EVAL_REQUEST_DELAY_MS) for free-tier rate limits
- Tier: `small`; model(s): `openai/gpt-oss-20b`
- **Prompt version: `answer-v2`** (read from `query_log.prompt_version` for every row)
- Retrieval: vector-only, top_k=6
- Refused (zero valid citations): 1/20 (not a quality metric; see Phase 2)
  - [acme] What is the on-call allowance per week? (query_log id 150)
- Requests that hit a 429 retry: 0/20
- Environment: in-process ASGI on WSL2, repo on /mnt/d, Postgres in Docker Desktop

**Baseline — clean: no request hit a 429 retry, so no backoff wait is included.**

| Metric | p50 (ms) | p95 (ms) | mean (ms) |
|---|---|---|---|
| End-to-end (total_ms) | 1094 | 2275 | 1173 |
| Retrieval (embed + vector search) | 72 | 527 | 172 |
| LLM call | 929 | 1633 | 1000 |

## Measurement notes

Retrieval latency is noisy on this machine (WSL2, Docker Desktop, repo on `/mnt/d`). In the
answer-v2 baseline run, with nothing else running against the Gateway stack, single queries'
retrieval took 527 ms and 1,377 ms against a typical 30–100 ms (query_log ids 157 and 165).
Treat small p50 movements between phases as noise, not signal; only large or consistent shifts
mean anything. LLM latency also varies with Groq load.

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

Reproduce all three numbers with:
`uv run python scripts/measure_dilution.py --tenant acme --question "What is the on-call allowance per week?" --document eng-runbook-on-call --section "Allowance and Time Off"`

Output on 2026-10-23: ISOLATED score 0.8026 (74 tokens embedded alone, above the top-6 cutoff);
MERGED score 0.5916, rank 27 of 133, chunk #1 (333 tokens), MISSED; top-6 cutoff 0.6293.
`scripts/diagnose_refusals.py ... --needle "PKR 15,000"` confirms the same merged rank and score.

Both scripts rank by vector similarity only; they document the vector-only baseline.
**Phase 5 success criterion:** with hybrid retrieval, `POST /v1/query` for this question must
retrieve the chunk holding the on-call allowance within its top 6 and answer with a valid citation.
