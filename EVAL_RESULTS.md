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

## Golden set baseline — Phase 2

Full run of all 100 golden-set items, 2026-10-23T19:03:11+00:00, by `uv run python eval/run_eval.py --baseline "Phase 2"`. Results: `eval/baselines/phase-2.json`.

- Generator: `openai/gpt-oss-20b` (tier `small`), prompt `answer-v2`; judge: `openai/gpt-oss-120b` (tier `large`), prompt `judge-v1`
- Retrieval: vector-only, tenant-wide, no ACL filter; answers use top 6; metrics at top 10
- Golden set hash `d58769e8532dd8e0`; corpus 251 chunks; commit `a9784a8-dirty`

| Retrieval (answerable items) | n | recall@5 | recall@6 | recall@10 | all-hops@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|
| all_answerable | 85 | 72.9% | 77.1% | 84.1% | 76.5% | 0.636 | 0.660 |
| single_hop | 50 | 76.0% | 82.0% | 88.0% | 88.0% | 0.635 | 0.693 |
| buried_fact | 20 | 80.0% | 85.0% | 90.0% | 90.0% | 0.640 | 0.701 |
| multi_hop | 25 | 56.0% | 58.0% | 70.0% | 44.0% | 0.617 | 0.554 |
| near_miss | 10 | 100.0% | 100.0% | 100.0% | 100.0% | 0.683 | 0.762 |

| Generation | rate | count / n |
|---|---|---|
| Refused unanswerable (hallucination guard) | 100.0% | 15 / 15 |
| Refused answerable (false refusals) | 11.8% | 10 / 85 |
| Faithful (judge, answered items) | 100.0% | 75 / 75 |
| Relevant (judge, answered items) | 100.0% | 75 / 75 |
| Correct (judge; refusals count as not correct) | 85.9% | 73 / 85 |
| Near-miss pairs with both answers correct | 100.0% | 5 / 5 |

Judge errors: 0. Hallucinated on unanswerable: none. Refused answerable: ['q022', 'q042', 'q101', 'q106', 'q051', 'q058', 'q060', 'q062', 'q064', 'q066'].

**Provenance and caveats (added by hand; every figure is readable from `eval/baselines/phase-2.json`):**
- Run in two sessions with `--resume`. Items 1–35 ran on 2026-10-23 from 17:15 UTC on one Groq account
  until it hit Groq's 200,000 tokens/day cap at q047; items 36–100 ran 18:05–19:03 UTC on a second Groq
  account. Same models, temperature 0, same code. Zero 429 retries and zero judge errors after the resume.
- Harness defect: on resume the run metadata was rebuilt, so `started_utc`, `elapsed_min` (58.1) and
  `git_commit` describe the resumed session only. The code was `a9784a8`; "-dirty" was uncommitted
  `CLAUDE.md` and spot-check files, not code.
- All 10 refused answerable items were retrieval misses, never model refusals with the evidence in hand:
  per-item `hop_ranks` show at least one hop outside the top 6 for every one (4 single-hop, 6 multi-hop).
- Faithful and relevant are 100% (75/75). Treat them as unverified until the hand spot-check of the judge
  is scored: q029 answered "20 April 2027" (the clearance meeting, not the report deadline) and the judge
  still marked it faithful.
- Buried-fact recall@6 is 85% (17/20), exactly the ceiling fixed before the harness was built.

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

**The buried-fact class in the golden set (20 items, tag `buried_fact`).** Selected on
structure only: the answer is a single sentence making up at most 6.5% (about 6%) of a gold
chunk of 300+ tokens. The 6.5% value was set after seeing three original items at 6.1%; no
item was chosen, kept or dropped because of its retrieval rank. Ten items were in the first
draft; the ten added later were fixed, together with an ordered reserve list, before any rank
was computed, and none needed replacing. `eval/verify_golden.py` enforces the rule. The Phase 5
claim is measured over all 20: "recall@6 on the buried-fact class rose from X% to Y%".
q101 rewords q022 (tag `buried_fact_paraphrase`, outside the 20). The same question ranked its
gold chunk 64th of 133 in one wording and 27th in the other: wording alone moves rank a lot.

**Phase 5 ceiling, fixed before the harness was built:** 17 of 20 buried-fact items already
rank in the top 6 under vector-only retrieval, tenant-wide and unfiltered. Maximum possible
gain on this class is 3 items (15 points). A smaller gain is not a failure; a gain larger than
this would mean the baseline moved for another reason and must be investigated.

Phase 3's ACL filtering shrinks each user's candidate pool, so these ranks will improve on their
own (q022 moves from 64th of 133 tenant-wide to 5th of 36 among chunks an engineer may read).
That improvement belongs to Phase 3. Phase 5 is judged only against the Phase 4 baseline, never
against the Phase 2 numbers, so a Phase 3 side effect cannot be read as a Phase 5 win.
**Phase 5 success criterion:** with hybrid retrieval, `POST /v1/query` for this question must
retrieve the chunk holding the on-call allowance within its top 6 and answer with a valid citation.
