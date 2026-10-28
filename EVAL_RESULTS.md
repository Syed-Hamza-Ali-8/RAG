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
- **Known limitation: citation correctness is not measured in this baseline.** The judge (judge-v1)
  checks claims against the whole source set, never whether the cited chunk supports the claim
  (calibration: 0/5 misattributed citations caught), and the runtime check only verifies that a cited
  label exists. "Faithful 100%" means every claim is supported somewhere in the context, not that
  citations point to the right chunk. judge-v2 adds a `citations_supported` verdict; it is first
  measured in the Phase 3 re-baseline.
- Gate: Phase 2 closed 2026-10-24 on the judge calibration below; the hand-labelled spot-check sheet
  (`eval/spotcheck/`) remains a human check on the calibration set itself.

## Judge calibration — judge-v1

Negative and positive controls, by `uv run python eval/calibrate_judge.py`; results in
`eval/calibration/judge-v1.json`. Judge `openai/gpt-oss-120b`, prompt `judge-v1`. The 20 items in
`eval/judge_calibration.jsonl` are synthetic answers over real Phase 2 baseline contexts, each with a
known flaw. Expected verdicts, catch rules and the fitness threshold (at least 80% of fabrications)
were committed in `8b1b823` before the judge saw any item.

| Category (5 each) | Caught when | Caught | Full expected verdict |
|---|---|---|---|
| Fabrication: value absent from every context chunk | faithful = false | 5 / 5 | 5 / 5 |
| Wrong question: true context fact, neighbouring question | correct = false | 5 / 5 | 4 / 5 |
| Bad citation: true fact cited to a chunk that lacks it | faithful = false | **0 / 5** | 0 / 5 |
| Good answer (false-negative check) | all three true | 5 / 5 | 5 / 5 |

**Verdict: fit to measure faithfulness and correctness** (fabrications 100%, no false negatives).
With 5 items per category the resolution is coarse: 5/5 is consistent with a true catch rate well
below 100%.

**Known blind spot: citation support.** judge-v1 never checks whether the cited chunk supports the
claim; its prompt says "citation markers such as [S1] are not claims", so it judges against the
whole source set. Its own reasons show it: for c13 it called the claim "supported by source S1"
while the answer cites S6. The runtime citation check only verifies that cited labels exist, so
nothing in the stack currently detects a misattributed citation. Faithfulness numbers from judge-v1
must not be read as "citations are correct".

c10 (the q029 pattern) was caught as not correct but judged "relevant"; the catch rule for this
category is correctness only, so it counts as caught.

Judge cost: 20 calls used 54,940 tokens (2,747 per call on average), logged in `query_log` with
`purpose = 'eval_judge'`. A full golden-set run makes about 85 judge calls, about 234,000 tokens:
more than the judge model's 200,000-token daily cap, so full runs exceed the daily budget of both
models.

### judge-v2 — pre-registered (`89feeab`), run 2026-10-26

judge-v2 adds a fourth verdict, `citations_supported`: every citation marker must point to a source
that supports its own sentence. The other three verdicts keep judge-v1's definitions. Its
calibration set, `eval/judge_calibration_v2.jsonl`, has 10 items per category (40): c01–c20 are the
judge-v1 items unchanged (its regression test), c21–c40 are new, built under the same mechanically
checked rules. Catch rules: fabrication → faithful = false; wrong question → correct = false; bad
citation → **citations_supported = false** (judge-v1's rule was faithful = false); good → all four true.
Pass rates, all required: fabrication ≥ 80% (the original bar), wrong question ≥ 80%, bad citation
≥ 80%, good ≥ 90% (at most one false negative). Not run yet: the judge model's daily budget on the
current account was nearly spent (an estimated 170,000 of 200,000 tokens) when judge-v2 was built.

**Result** (`eval/calibration/judge-v2.json`; judge `openai/gpt-oss-120b`, prompt `judge-v2`):

| Category (10 each) | Caught when | Pre-registered | Caught | Full expected verdict |
|---|---|---|---|---|
| Fabrication | faithful = false | ≥ 80% | 10 / 10 (100%) | 10 / 10 |
| Wrong question | correct = false | ≥ 80% | 10 / 10 (100%) | 9 / 10 |
| Bad citation | citations_supported = false | ≥ 80% | **10 / 10 (100%)** | 10 / 10 |
| Good answer (false-negative check) | all four true | ≥ 90% | 9 / 10 (90%) | 9 / 10 |

**Verdict: FIT.** Every category meets its pre-registered rate. The blind spot judge-v1 had on
citations is closed (bad citations 0/5 under judge-v1, 10/10 under judge-v2), including all five
judge-v1 bad-citation items (c11–c15).

- **The one false negative, c20** (a judge-v1 item, passed by judge-v1): the answer gives the
  GBP 3 million liability cap; the reference adds that the cap does not apply to fraud or dishonesty.
  judge-v2 marked it not correct: "omits ... a key fact". judge-v2 is stricter than judge-v1 about
  omitted qualifiers. This is the single miss the good-answer bar allows (at most one).
- **c10** is again caught as not correct but judged "relevant", as under judge-v1; the catch rule for
  wrong-question items is correctness only.
- Cost: 40 calls, 118,963 tokens (2,974 per call on average; judge-v1 averaged 2,747). One transient
  connection failure stopped the run after 14 items; it resumed from the saved verdicts without
  re-judging them.

## Golden set — Phase 3 re-baseline: pre-registered expectations (fixed 2026-10-24, before the run)

From Phase 3 the harness retrieves each golden item as its seeded `as_user`, through the SQL ACL
predicate. Nothing else that ranks chunks changed: same corpus, chunker, embedding model, prompt
(answer-v2) and top-k. The only other retrieval change is `hnsw.iterative_scan = strict_order`,
which keeps the index scanning until LIMIT permitted rows are found in exact distance order.

- **Expected: retrieval numbers IMPROVE** (recall@5/6/10, MRR, nDCG@10, multi-hop all-hops@10).
  This is a **mechanical side effect of ACL filtering, not a retrieval improvement**. A user's
  permitted chunks are a subset of the tenant's, ranked in the same order, so chunks the user may
  not read drop out from above each gold chunk. It must not be described as a retrieval gain
  anywhere (README included); the README attributes it to the candidate pool shrinking.
- **q022** is expected to move from rank 64 of 133 (tenant-wide, Phase 2) to about 5th of the 36
  chunks an engineer may read, which is inside the top 6 the model sees. It is a Phase 2 false
  refusal caused by a retrieval miss; at rank ~5 the refusal is expected to disappear. Whether the
  model then answers correctly is not predicted.
- **No gold rank may get worse.** By the subset argument above, an answerable item's gold chunk
  can only keep or improve its rank. Any item whose rank worsens is investigated before the
  baseline is accepted: either HNSW approximation (shown by re-checking with an exact scan) or a
  bug. A gold chunk the item's own user cannot read is a golden-set construction error, not a result.
- **Generation numbers:** no direction predicted. The top 6 contents change for many items, so
  correctness and refusals can move either way; they are reported, not claimed.
- **Judge-scored numbers are not comparable with Phase 2** (added 2026-10-26, after judge-v2
  calibration and before the run). Phase 2 was scored by judge-v1, Phase 3 by judge-v2. judge-v2 is
  stricter about omitted qualifiers (calibration item c20), so "correct" may fall partly because
  the judge changed. Phase 3 correctness and faithfulness are reported on their own; a fall from
  Phase 2's 85.9% is not read as a regression. `citations_supported` has no Phase 2 value; Phase 3
  sets its first baseline. Retrieval metrics and refusal counts use no judge and stay comparable.
- **Comparisons:** Phase 3 vs Phase 2 is reported only as the ACL side effect described here.
  Phase 4 is judged against the Phase 3 baseline, and Phase 5 against Phase 4 (unchanged rule).

## Golden set baseline — Phase 3

Full run of all 100 golden-set items, 2026-10-28T10:35:06+00:00, by `uv run python eval/run_eval.py --baseline "Phase 3"`. Results: `eval/baselines/phase-3.json`.

- Generator: `openai/gpt-oss-20b` (tier `small`), prompt `answer-v2`; judge: `openai/gpt-oss-120b` (tier `large`), prompt `judge-v2`
- Retrieval: vector-only, ACL-filtered in SQL as each item's seeded `as_user`; answers use top 6; metrics at top 10
- Golden set hash `d58769e8532dd8e0`; corpus 251 chunks; commits `4ce3880`, `9345912` (the second only fixes the stop message)
- Three sessions: 2026-10-26 (29 items, stopped by the budget day plan), 2026-10-28 (18 items, stopped by a
  transient connection failure at q109), 2026-10-28 (53 items, finished)

| Retrieval (answerable items) | n | recall@5 | recall@6 | recall@10 | all-hops@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|
| all_answerable | 85 | 84.1% | 86.5% | 92.9% | 87.1% | 0.700 | 0.728 |
| single_hop | 50 | 88.0% | 92.0% | 98.0% | 98.0% | 0.679 | 0.752 |
| buried_fact | 20 | 90.0% | 90.0% | 95.0% | 95.0% | 0.673 | 0.740 |
| multi_hop | 25 | 70.0% | 70.0% | 80.0% | 60.0% | 0.748 | 0.667 |
| near_miss | 10 | 100.0% | 100.0% | 100.0% | 100.0% | 0.683 | 0.762 |

| Generation | rate | count / n |
|---|---|---|
| Refused unanswerable (hallucination guard) | 100.0% | 15 / 15 |
| Refused answerable (false refusals) | 7.1% | 6 / 85 |
| Faithful (judge, answered items) | 100.0% | 79 / 79 |
| Relevant (judge, answered items) | 100.0% | 79 / 79 |
| Citations supported (judge-v2, answered items) | 93.7% | 74 / 79 |
| Correct (judge; refusals count as not correct) | 90.6% | 77 / 85 |
| Near-miss pairs with both answers correct | 100.0% | 5 / 5 |

Judge errors: 0. Hallucinated on unanswerable: none. Refused answerable: ['q106', 'q051', 'q052', 'q058', 'q064', 'q066'].

### Phase 3 vs Phase 2, read through the pre-registered expectations

**Retrieval moved as predicted, and the movement is the ACL side effect, not a retrieval gain.**
Nothing that ranks chunks changed except that each item is now retrieved as its seeded user, whose
permitted chunks are a subset of the tenant's. Recall@6 on answerable items went from 77.1% to 86.5%
(recall@10 84.1% → 92.9%, MRR 0.636 → 0.700, multi-hop all-hops@10 44% → 60%). None of these is a
retrieval improvement and none may be quoted as one; the README attributes them to the smaller
candidate pool.

- **No gold rank may get worse: held.** Per hop, 23 ranks improved, 87 are unchanged, 0 got worse.
- **q022: held.** Rank 64 of 133 tenant-wide (outside the top 10) → **5th**; no longer refused, and
  judged correct. q101 (its rewording) moved from outside the top 10 to 4th.
- **Phase 5 criteria re-based.** Buried-fact recall@6 is now 90% (18/20) and multi-hop all-hops@10 60%
  (15/25); Phase 5 is still judged against Phase 4, never against these or Phase 2's values.

**Refusals (no judge involved; comparable).** Unanswerable items: 15/15 refused in both phases. False
refusals on answerable items: 10 → 6. q022, q042, q060, q062 and q101 are no longer refused, each because
a missing gold chunk now ranks in the top 6. Five refusals remain for the Phase 2 reason, a hop outside the
top 6 (q051, q058, q064, q066 multi-hop; q106 at rank 10). One is new:

- **q052 is a truncated generation, not a refusal.** Its retrieval improved (hop ranks [2, —] → [1, 7]).
  `query_log` id 462: 700 completion tokens, exactly `LLM_MAX_COMPLETION_TOKENS`, and an empty answer;
  the zero-citation check turned the empty text into a refusal. It is the only empty answer of 102
  generation calls in the run. Recording a length cut-off as a refusal is close to the silent fallback
  invariant 7 forbids; fixed afterwards (see "Corrections after the Phase 3 gate" below).

**Corrected refusal counts (2026-10-28).** The refusal counts above mix two outcomes. Read them as:

| | Refused (answerable) | Truncated | As recorded |
|---|---|---|---|
| Phase 2 baseline | **9** | 1 (q060, `query_log` 253) | 10 |
| Phase 3 baseline | **5** | 1 (q052, `query_log` 462) | 6 |

Both truncations have the same signature (700 completion tokens, empty answer) and were found by
migration 009's backfill; no other row matches. The Phase 2 write-up's "all refusals are retrieval misses"
holds for the 9 true refusals. The baseline JSON files are left as run; this table is the correction.

**Judge-scored numbers: not comparable with Phase 2** (pre-registered 2026-10-26). Correct went from
85.9% (judge-v1) to 90.6% (judge-v2); that difference mixes the ACL effect, five fewer refusals and a
stricter judge, and is not read as a change in answer quality. Where the verdicts differ on items
answered in both phases: q109 correct under judge-v1, not correct under judge-v2 ("omits ... no
additional egress charge", the c20 pattern); q057 the reverse. Faithful is 100% under both judges.

**citations_supported (first baseline): 93.7%, 74/79 answered items.** The five misattributed citations:
q019, q029, q037, q063, q070. This is the gap judge-v1 could not see; Phase 2 has no value for it.

### Citation misattribution: what the five failures look like (recorded before Phase 4/5)

Examined 2026-10-28 so that a change in which chunks are available (hybrid retrieval, Phase 5) can be
compared against what the failure looked like here. Not fixed; no prompt or code change.

- **Every one is a stacked double citation.** All five answers end one sentence with two markers
  (`[Sx][Sy]`) and the judge rejects one of the pair. Base rate: 22 of 79 answered items stack two
  markers and 5 of those 22 are flagged (23%); none of the 57 single-marker answers is flagged.
- **Single-hop, correct answers, one extra citation (q019, q037).** The first marker is the gold chunk and
  supports the claim; the second is a related chunk from a *different* document that lacks the key fact
  (q019: `hr-employee-handbook#5` has no "Priya Raman"; q037: `public-service-catalog#0` has no
  15 January to 31 March range). The answer is right; the second citation is decoration.
- **Multi-hop, one compound sentence over two hops (q063, q070).** One sentence states both hops and
  cites two chunks; one cited chunk is the *adjacent chunk of the right document* rather than the gold
  chunk, although the gold chunk was among the six sources (q063 cites `eng-postmortem-2026-03-atlas-outage#9`
  where gold #8 was S5; q070 cites `eng-platform-architecture#2` where gold #1 was S1). Both answers are
  judged correct. Sentence-level checking also penalises a sentence whose halves are each supported by
  a different marker; that interacts with this pattern.
- **A wrong answer, not a citation slip (q029).** The known neighbouring-fact item (the c10 pattern): the
  gold chunk ranks 9th, outside the six sources, and the model gives the audit-committee meeting date
  (20 April 2027) instead of the report deadline (30 April 2027), citing two other chunks of the same
  engagement letter. Judged not correct; the misattribution is a symptom of the retrieval miss.
- **Stable across phases, not caused by the ACL.** q019, q063 and q070 cited exactly the same chunks in
  Phase 2; judge-v1 had no way to flag them.

What to watch in Phase 5: whether the stacked-marker rate or the adjacent-chunk substitution changes when
FTS and graph paths add neighbouring chunks to the six sources; q029 should change only if its gold chunk
enters the top 6.

### Corrections after the Phase 3 gate (2026-10-28)

- **Truncation is its own outcome.** The provider raises `TruncatedCompletion` when the finish reason is
  `length`; `/v1/query` logs and audits the query, then returns HTTP 502 `llm_truncated` (never a refusal).
  `query_log.outcome` (migration 009) is `answered`, `refused` or `truncated`; eval reports list truncations
  separately and leave them out of both refusal rates. `LLM_MAX_COMPLETION_TOKENS` raised from 700 to 1000.
- **q052 re-run alone at 1000 tokens: it completes (650 tokens) and refuses; it does not answer.** The
  refusal is genuine. Its second hop, Mei Lin Zhou's role, is readable by its user (`finance@acme`) only
  in `public-company-overview#0`, which ranks 7th, outside the six sources. Phase 2 answered q052
  correctly by citing `eng-platform-architecture#0`, which is restricted to the engineering role: an
  answer only possible because Phase 2 retrieval had no ACL. q052 now belongs with q051, q058, q064 and
  q066 (a hop outside the top 6), so at the corrected limit the Phase 3 refusal count would be 6 again,
  all genuine. That is a single re-run, not a baseline; the next full run measures it.
- **Network retries have their own policy.** Connection errors and timeouts retry up to 8 times, 2 s
  doubling to a 30 s cap (about two minutes of waiting), separate from the 429/5xx budget, so the 10 s
  blips that stopped the baseline and the calibration on 2026-10-26 no longer stop a run.

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

### Multi-hop questions whose hops are not all retrieved

**Second pre-registered Phase 5 criterion, fixed 2026-10-24 before any Phase 3–5 work.** Multi-hop
all-hops@10 is the weakest number in the Phase 2 baseline: 11 of 25 (44%) multi-hop items have
every hop's evidence in the top 10 (8 of 25, 32%, in the top 6 the model actually sees). Six of the
ten false refusals in the baseline are multi-hop items with a hop missing from the top 6. The 14
items failing all-hops@10 are q051, q052, q054, q056, q058, q060, q062, q064, q067, q068, q069,
q070, q073 and q075 (from per-item `hop_ranks` in `eval/baselines/phase-2.json`).

- **Measure:** all-hops@10 on the 25 multi-hop items, the same items and metric as here. Also report
  all-hops@6, which bounds what the model can answer.
- **Comparison:** Phase 5 is judged against the Phase 4 baseline's value, never this Phase 2 value.
  Any movement between Phase 2 and Phase 4 (Phase 3's ACL filtering shrinks candidate pools) belongs to
  those phases. The Phase 5 claim reads "multi-hop all-hops@10 rose from X% (Phase 4) to Y%".
- **Ceiling:** 25 of 25. Unlike the buried-fact class there is real headroom (up to 14 items from here),
  so a large gain is possible. A gain on this class with no change in single-hop recall is the expected
  signature of graph traversal working; a single-hop regression must be reported alongside it.
- No item may be added to, removed from or reworded in the multi-hop class to move this number. If the
  golden set changes for another reason, the criterion is re-stated on the new set before Phase 5 runs.
