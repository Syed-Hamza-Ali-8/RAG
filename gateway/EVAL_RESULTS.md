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

**Field data point (2026-10-29, Phase 4 cache sweep): the judge contradicted itself on identical
content.** q054's answer and sources were judged twice, once for the original question
(`citations_supported` true) and once for its UPPERCASE variant (false: "S4 and S2 do not explicitly
state the EUR 1,900 amount", a figure derived as 5% of EUR 38,000 and cited with stacked markers). Same
answer, same sources, different verdict: a judge reliability fact, not a cache fault. Across the sweep's
40 served answers `citations_supported` was 39/40, against 10/10 on the calibration set's good answers;
calibration items were constructed to be clear-cut, and the real-world false-negative rate on this
verdict is likely higher than calibration implied. Derived figures and stacked citations are where it
showed.

**Second field data point (2026-10-30, Phase 4 routing).** q005's small- and large-tier answers give the same
dates and both omit the auditor (Nordcert); the judge passed the small answer as correct and failed the large
one for "omitting the auditor". Same substance, opposite `correct` verdicts. Single-item verdict differences
between conditions should be read with this in mind; aggregate differences of one item are within it.

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

Added 2026-11-01 (Phase 4 Run A), the before-picture for Phase 5: **q051's unsupported citation.** With one hop
missing from its six sources, the model answered the hop it could see and wrote that "the sources give no
contract end date", citing a chunk (S2) that does not support that claim; judge-v2 marked it unfaithful, the
only unfaithful answer in Run A (79/80). A citation attached to a statement about what the sources *lack* is
a distinct failure from the stacked-marker pattern above. Hybrid retrieval changes which chunks are available
to cite: watch whether q051's missing hop enters the sources (then the claim disappears), and whether
partial answers of this kind (q051, q058) become more or less common.

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

## Phase 3 gate: evidence (measured 2026-10-28; recorded here 2026-11-01)

Reported at the gate and in commit messages (`7f32d3f`) but not written here at the time; recorded now so every
summary figure traces to this file.
- **Isolation suite, zero leaks:** `tests/test_acl_isolation.py` and `tests/test_admin_isolation.py` 151/151 passed
  (43 retrieval probes, 19 admin-surface probes, each checked under P1-P4).
- **Removing the ACL predicate makes the suite fail:** with `--acl-disabled`, all 39 leak probes fail (85 other tests,
  which do not depend on the predicate, pass); an always-on mutation test re-proves each probe leaks without it.
- **Audit row for every query, with denied-chunk counts:** the Phase 3 baseline's 101 generation queries produced 101
  `audit_log` rows: none missing, none duplicated, no null `denied_count`, no empty `retrieved_ids`; 60 rows record
  denied chunks (1.86 per query on average).
- **Overlapping titles, cross-tenant queries return nothing:** 11 document titles exist in both tenants; asking each,
  in two phrasings, as six users (three per tenant) through the production ACL-filtered search at top-k 20: 132
  queries, 2,640 chunks returned, 0 from the other tenant.

## A correct answer that should never have been possible (q052)

q052 asks, as `finance@acme.example`: "Who is the business owner of the vendor that hosts Atlas, and
what is that person's role at Acme?" In the Phase 2 baseline it was answered, cited and judged correct:
"Mei Lin Zhou ... is Acme's Chief Technology Officer." One of the two citations was
`eng-platform-architecture#0`, a chunk restricted to the engineering role. A finance user may not read
it. Phase 2 retrieval had no ACL filter, so the chunk reached the model, the model used it, and every
check passed. Nobody noticed.

Phase 3 put the ACL predicate in the SQL. The engineering chunk is no longer retrieved for this user.
The only chunk the user may read that holds her role, `public-company-overview#0`, ranks 7th, outside
the six sources, so the model names the business owner, cannot state her role, and refuses. Re-run
alone at the corrected completion limit (1000 tokens), it completes and refuses again. The honest
consequence of closing the leak is one fewer answered question.

It was not the only leak. Checking every Phase 2 citation against its item's user with the same rule the
isolation suite uses: **11 Phase 2 answers cited at least one chunk their user may not read (10 judged
correct), and 187 restricted chunks were among the six sources the model saw across the 100 items.**
In Phase 3 both counts are **0**. For ten of the eleven (q003, q013, q016, q026, q037, q053, q054, q057,
q075, q091) the same fact also exists in a chunk the user may read, and Phase 3 answers them correctly
from those; q052 is the one whose answer existed only through the leak at the depth the model sees.

This is a better illustration of what Gateway is for than any adversarial probe, because it was not
constructed: the golden set was written to measure answer quality, every gold chunk is readable by its
user, and the leak was found in the answers, not planted in the questions. Without permission-aware
retrieval, an assistant over a firm's documents can be right for a reason the asker was never allowed to
see, and a quality metric will score it as a success.

## Phase 4 semantic cache: pre-registered finding (fixed 2026-10-28, before any cache code)

**Pure embedding similarity cannot safely gate a cache on this corpus.** Measured with the production
embedder (`BAAI/bge-small-en-v1.5`), cosine between the two questions of each golden near-miss pair:

| Pair | Questions | Cosine |
|---|---|---|
| nm4 | maternity leave / paternity leave | 0.9124 |
| nm1 | per diem in the UAE / in the United Kingdom | 0.9145 |
| nm3 | minimum salary, Manager (C1) / Senior Manager (C2) | 0.9216 |
| nm5 | expense claim of USD 2,000 / USD 5,000 | 0.9540 |
| nm2 | Service Credit below 99.9% but at least 99.0% / below 99.0% | **0.9948** |

The golden set's only real paraphrase (q101, a rewording of q022) sits at **0.8190**. nm2 is above the
whole planned sweep (0.88-0.99), so no threshold in it keeps nm2 apart, and any threshold that kept it
apart (>0.9948) would also refuse every paraphrase.

**Decision (user-approved): a content-word check on top of the threshold.** A cache hit additionally
requires the same content words as the stored question (lowercased, punctuation and stopwords removed,
numbers kept). It separates all five pairs, including nm4, which differs only in an ordinary word.

**Consequences, stated before the results:**
- The cache serves near-verbatim repeats (same content words in any case, punctuation or order), not
  paraphrases. That caps the achievable hit rate; the gate's hit-rate measurement is a repeated-query
  workload, and a low hit rate on paraphrased traffic is expected, not a defect.
- The similarity threshold is no longer the safety mechanism. It is a second filter below the word
  check. The sweep (0.88-0.99) still runs and its curve is recorded, but every point is measured **with
  the word check on**, and the claim it supports is narrower: hit rate and faithfulness among questions
  that already share their content words.
- Only answered outcomes are stored; refusals and truncations never are (a cached refusal served to a
  user with more access is a correctness bug). Entries expire after `CACHE_TTL_HOURS` (default 24).
- The temporal/entity bypass list (today, yesterday, now, current, currently, latest, "as of", "to
  date", this/last/next week/month/quarter/year, "for client …", "for customer …") has a cost: the number
  of golden-set questions it excludes is reported with the implementation, not assumed.
- Rejected: a bypass for every question containing a number or code (too blunt on a corpus of fees,
  dates and limits) and a retrieved-chunk overlap check (near-miss pairs share their gold chunk).

**Built 2026-10-28 (before any tuning):**
- **Bypass list cost: 2 of 100 golden questions** never touch the cache: q056 ("…what setting must be
  used *now*?") and q074 ("Sunridge's *current* annual fee"), both genuinely time-sensitive. The first
  version also caught q024 ("for client-requested weekend work"): "for client" matched across the
  hyphen. The pattern now requires a following name ("for client <name>"), so q024 is cacheable.
- **Isolation suite: 73/73 pass** (`tests/test_cache_isolation.py`): the 28 probes, the five near-miss
  pairs at each sweep threshold 0.88/0.92/0.95/0.99 with the word check on, and the mutation checks:
  without the role signature every cross-role/clearance probe is served the wrong entry (with the
  restricted value where it has one); without the tenant scope both cross-tenant probes leak; without the
  word check at 0.88 all five near-miss pairs are served each other's answers.
- **A second layer, measured on its own.** Before a hit is served, its cited chunks are re-checked against
  the caller's ACL in SQL. With the signature removed from the key, that re-check alone still stops every
  restricted value (8/8 probes). It does not stop k09 (an employee's answer served to HR), which cites
  chunks HR may read: the key, not the re-check, is what keeps entries per permission set.
- **Invalidation is enforced by the database** (migration 003 triggers on `documents` and `chunks`): any
  insert, update or delete wipes that tenant's entries, whatever the write path.
- One construction gap found and fixed during the build: k06/k18/k28's question did not retrieve the
  restricted value for its populating user, so a leak could not have shown; the verifier now requires it
  (commit `773f59c`).

## Phase 4 cache threshold sweep: design and predictions (fixed 2026-10-28, before any real run)

**Design (user-approved).** Thresholds 0.88, 0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99 on the fixed
25-item subset, cache cleared before each. Phase A (cold): the 25 questions; nothing can hit, so it
measures the lookup's cost on the miss path (`query_log.cache_lookup_ms`, migration 010). Phase B (warm),
immediately after: the 25 again, then per item an exact repeat, a case/punctuation variant and a genuine
paraphrase (`eval/cache_workload.jsonl`, committed with this section). Recorded per threshold: the three
hit rates, faithfulness and correctness of served answers (judge-v2), p50 latency of hits and misses.
**Hard gate at every threshold:** the full cache isolation suite passes (it includes the five near-miss
pairs) and no hit serves another item's answer. A threshold that fails either is not a candidate.

**Method, to fit the free-tier budget** (`eval/cache_sweep.py`). The real model answers each of the 25
questions once (`--record`, cache off). The sweep then replays those recorded answers on misses: the
cache's decisions do not depend on generated text, and every answer a hit can serve is the recorded real
answer of the item's own question (asserted per hit). Re-running the model at every threshold would cost
about 585 generation calls (~1.3M tokens, a week of budget) to produce answers the measurement never
looks at. Consequences: miss latency in the table excludes the model (the recorded real LLM latency is
reported beside it), and each distinct served (question, answer) pair is judged once, not per threshold.

**Workload properties (measured, `cache_sweep.py --check`, no LLM):**
- Variants keep their content words (one case, `5,000` → `5000`, exposed a gap: the content key now drops
  thousands separators; decimal points still count). Variant cosine to its original: 0.973-1.000.
- No paraphrase keeps all of its question's content words. Paraphrase cosine: 0.862-0.985, several above
  every near-miss pair's cosine, which is the pre-registered finding again from the other side.

**Predictions:**
- **Paraphrase hit rate: 0/25 at every threshold.** The word check rules every paraphrase out before the
  threshold applies. This is the measured cost of the word check.
- Exact repeats and re-runs hit for every item the model answered when recorded, minus q074 (bypassed:
  "current"); refused items are never stored.
- Variants hit for every cacheable item whose variant cosine reaches the threshold: all of them up to
  0.97; at 0.98 q100 (0.9731) misses; at 0.99 q107 (0.9831), q088 (0.9868), q052 (0.9800) and q100 miss.
- Served answers are the item's own recorded answers, so served-answer faithfulness should match the
  recorded answers' faithfulness at every threshold; a drop at a low threshold would mean a wrong hit.
- One more measured fact: q074's paraphrase ("…at present…") escapes the bypass list, which is lexical.
  It cannot hit (different content words), but the list does not catch every temporal phrasing.

## Phase 4 cache threshold sweep: results (2026-10-29)

Run by `eval/cache_sweep.py` (`--record`, `--sweep`, `--judge`, `--report`); artifacts in
`eval/cache_sweep/` (recording, sweep, verdicts). Recording: 25 real generations (`openai/gpt-oss-20b`,
answer-v2), **21 answered and 4 refused** (q079, q083, q088 unanswerable; q052, as in Phase 3). Refused
items are never stored; q074 is bypassed ("current"). So **20 of 25 items are cacheable**, and 20/25 is
the ceiling for every hit rate below.

| Threshold | Exact | Variant | Paraphrase | Re-run | Served: faithful / correct | p50 hit | p50 miss (excl. model) | Lookup p50, cold | Wrong-item hits | Isolation suite |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.88 | 20/25 | 20/25 | 0/25 | 20/25 | 60/60 / 60/60 | 26 ms | 27 ms | 1 ms | 0 | 98/98 |
| 0.90 | 20/25 | 20/25 | 0/25 | 20/25 | 60/60 / 60/60 | 23 ms | 27 ms | 1 ms | 0 | 98/98 |
| 0.92 | 20/25 | 20/25 | 0/25 | 20/25 | 60/60 / 60/60 | 24.5 ms | 28 ms | 1 ms | 0 | 98/98 |
| 0.94 | 20/25 | 20/25 | 0/25 | 20/25 | 60/60 / 60/60 | 25 ms | 29 ms | 1 ms | 0 | 98/98 |
| 0.95 | 20/25 | 20/25 | 0/25 | 20/25 | 60/60 / 60/60 | 27 ms | 34 ms | 1 ms | 0 | 98/98 |
| 0.96 | 20/25 | 20/25 | 0/25 | 20/25 | 60/60 / 60/60 | 24 ms | 28 ms | 1 ms | 0 | 98/98 |
| 0.97 | 20/25 | 20/25 | 0/25 | 20/25 | 60/60 / 60/60 | 25 ms | 27 ms | 1 ms | 0 | 98/98 |
| 0.98 | 20/25 | **19/25** | 0/25 | 20/25 | 59/59 / 59/59 | 25 ms | 26.5 ms | 1 ms | 0 | 98/98 |
| 0.99 | 20/25 | **18/25** | 0/25 | 20/25 | 58/58 / 58/58 | 24.5 ms | 28 ms | 1 ms | 0 | 98/98 |

- **Every threshold passes the hard gate**: the full isolation suite (all five near-miss pairs included)
  and no hit serving another item's answer.
- **The curve is flat from 0.88 to 0.97.** The content-word check decides every hit before the threshold
  applies; the threshold only starts to bind above the lowest variant cosine (0.973), costing one variant
  at 0.98 (q100) and two at 0.99 (q100, q107).
- **Served answers: 40 distinct (question, answer) pairs judged once each (judge-v2): faithful 40/40,
  relevant 40/40, correct 40/40, citations supported 39/40.** The one exception is q054's UPPERCASE variant,
  served the same answer and sources as q054's original question, which the judge passed: a judge
  disagreement on identical content (a derived figure, 5% of EUR 38,000, cited with stacked markers),
  not a cache effect.
- **Latency.** Real model p50 1,106 ms (recording). A hit returns in 23-27 ms p50; a miss costs about
  27 ms plus the model. The lookup itself on the miss path: p50 1 ms, p95 3 ms, max 21 ms (216 cold
  lookups). Retrieval p50 25 ms with the cache off vs 31 ms with it on: within this machine's documented
  noise, and the direct lookup timing is the number to trust.

**Pre-registered predictions:**
- **Held: paraphrase hit rate 0/25 at every threshold.** The measured cost of the word check.
- **Held: exact repeats and re-runs hit every item the model answered, minus q074** (21 − 1 = 20).
- **Held where testable: variant misses.** All cacheable variants hit up to 0.97; q100 misses at 0.98;
  q100 and q107 miss at 0.99, as named. **Untestable:** q052 and q088, also named for 0.99, were refused
  when recorded, so they were never stored and their variants could not hit at any threshold. **Missed in
  the prediction:** q074's variant also contains "current", so it is bypassed at every threshold; the
  prediction listed q074 only under exact repeats.
- **Held: no drop in served-answer quality at low thresholds** (faithful and correct 100% at all nine).
- **Held: q074's paraphrase ("at present") escapes the bypass list** and still cannot hit.

**Chosen threshold: 0.95 (user decision, 2026-10-29). It is not a tuned optimum.** The curve is flat from
0.88 to 0.97, identical hit rates and identical safety, because the content-word check decides every hit
before the threshold applies. 0.95 is the midpoint of that flat region: enough margin above 0.88 that a
corpus or embedding-model change does not immediately put the threshold in play, and below 0.973, where
legitimate variants start being lost. **The threshold alone is not a safety mechanism:** if the word check
were ever removed, no value in the swept range would keep nm2 (0.9948) apart.

**A tooling bug, caught before it cost anything.** The first `--judge` attempt counted 537 distinct served
answers instead of 40: each run record merged the `query_log` row, whose `id` column overwrote the item id.
The judge pre-flight refused (1.5M tokens needed), so no tokens were spent. Fixed (`query_log_id`); the
sweep file was repaired by plan position with every run's kind, question and type verified (1,125 runs),
so the sweep did not need to be re-run. The per-hit wrong-item assertion used the real item id throughout.

## Phase 4 routing: design, criteria and predictions (fixed 2026-10-29, before any routing code or measurement)

**What routing can win on this corpus, from existing data.** The small model (`openai/gpt-oss-20b`) is
correct on 24 of the 25 subset items in the Phase 3 baseline (judge-v2). The one failure, q052, is a
retrieval miss (its second hop ranks 7th, outside the six sources). On the full golden set it fails 8 of
100: seven retrieval misses (q051, q052, q058, q064, q066, q106 refused with a hop outside the top 6;
q029 answered with a neighbouring date, gold chunk at rank 9) and q109 (judge-v2's stricter reading of an
omitted qualifier). A larger generator sees the same six chunks.

**Classifier** (spec task 5: cheap heuristics first). A score in [0, 1], a weighted sum of features each
scaled to [0, 1]. Weights are fixed here by judgement, not fitted to outcomes, so 25 items cannot overfit
them:

| Feature | Value | Weight |
|---|---|---|
| Multiple questions ("…, and what/how/which/when/who/where…") | 1 if present | 0.25 |
| Clause count (commas, and/or/if/which/that/while/whereas) | min(n / 3, 1) | 0.15 |
| Entity count (capitalised words not first in the question, numbers) | min(n / 4, 1) | 0.15 |
| Question length | min(words / 30, 1) | 0.10 |
| Comparative/superlative terms (more, less, most, least, higher, lower, than, versus, compare, difference, …) | 1 if present | 0.10 |
| Temporal markers (before, after, during, since, until, by the end, deadline, month, quarter, year, 20xx) | 1 if present | 0.05 |
| Low retrieval confidence | 1 − top-1 cosine | 0.10 |
| Flat retrieval scores | 1 − min((top-1 − top-6) / 0.2, 1) | 0.10 |

**Policy** (spec task 6). Score ≥ `ROUTING_THRESHOLD` → large tier, else small. Both tiers come from `.env`
(both Groq); the router picks between configured tiers and never falls back from one to the other.

**Measurement** (cache off; record-and-replay as in the cache sweep):
- Subset (25 items): small answers = the 25 recorded on 2026-10-29 for the cache sweep (answer-v2, cache
  off); large answers = 25 new recordings on the large tier with the same retrieval. Judge-v2 for every
  answer not already judged.
- Supplement: the seven other Phase 3 small-model failures (q029, q051, q058, q064, q066, q106, q109),
  recorded on both tiers and judged. It exists because the subset holds a single failure, so on its own
  it cannot show an item where the large model helps even if one exists. Reported separately.
- Routing is replayed at thresholds 0.0 (always large), 0.1 … 0.9 and 1.01 (always small): each item's
  outcome is the chosen tier's judged answer, and its cost is that answer's tokens at that tier's price.

**Labels.** An item is *ok* on a tier if its answer is judged correct, or if it is unanswerable and refused.
*Needs large*: not ok on small, ok on large. *Small better*: ok on small, not ok on large.

**Reported per threshold:** share routed to large, correctness, faithfulness on answered items,
refusals, shadow cost, LLM latency p50 (recorded), and how many *needs large* items it catches.

**Shadow cost** (spec task 7): `query_log.est_cost_usd` = prompt tokens × input price + completion tokens ×
output price of the tier used, with prices from `.env`. Groq list prices per 1M tokens (console.groq.com/
docs/models, read 2026-10-29): gpt-oss-20b USD 0.075 in / 0.30 out; gpt-oss-120b USD 0.15 in / 0.60 out.
No price set → NULL, never a guessed number. Cache hits cost 0.

**Acceptable delta** (for the gate's "faithfulness with routing vs always-large"): on the subset, routed
correctness and faithfulness within 1 item (4 points) of always-large; on the full gate run, within 3 points.

**"Underperform", which would justify an LLM classifier:** the *needs large* set is non-empty AND no
threshold that routes at most half of the traffic to the large tier catches at least half of those items
while staying within the acceptable delta. If *needs large* is empty, the heuristics cannot underperform
on this data, and an LLM classifier is not justified by it.

**Predictions:**
- *Needs large* on the subset: **0 items.** q052 also fails on the large tier (the role is not in its six
  chunks); always-large and always-small correctness are within 1 item.
- The large tier costs twice as much per token and, as a reasoning model, likely spends more completion
  tokens, so every threshold that routes anything to it costs more for no measurable quality gain.
  Always-small meets the acceptable delta at the lowest cost.
- Supplement: the six retrieval-limited refusals stay refused on the large tier. q029 and q109 are the only
  plausible *needs large* items (or *small better*: the large tier may refuse q029 rather than give the
  wrong date, which is not "correct" either).
- Sanity check of the features, independent of outcomes: multi-hop questions score higher on average than
  single-hop ones.

## Phase 4 routing: results (recorded 2026-10-29, judged 2026-10-30)

Recorded by `eval/routing_sweep.py --record` (64 answers: 25 subset + 7 supplement items, both tiers, cache
off; `eval/routing_sweep/recording.jsonl`); judged 2026-10-30 (26 answers, judge-v2, 0 errors;
`eval/routing_sweep/verdicts.jsonl`). The first judging attempt on 2026-10-29 was refused by its budget
pre-flight; the parts below headed "decided without the judge" were written and committed before judging.

**Decided without the judge:**
- **Subset: *needs large* = 0 items** (prediction held). The small tier fails only q052, and the large tier
  refuses it too: the role it needs is not among the six chunks either model sees. q079, q083, q088
  (unanswerable) are refused by both tiers.
- **Supplement:** q058, q064, q066, q106 are refused by both tiers (prediction held: retrieval-limited stays
  refused). Open until judged: q051 (small truncated at 1,000 tokens, large answered), q029 and q109 (both
  tiers answered).
- **Possible regression:** q074 is answered by the small tier and refused by the large tier.

**Routing curve, subset (25 items).** Judged 2026-10-30.

| Threshold | Sent to large | Correct | Faithful (answered) | Refused | Shadow cost (USD) | LLM p50 |
|---|---|---|---|---|---|---|
| 0.0-0.1 (always large) | 25/25 | 22/25 | 20/20 | 5 | 0.010696 | 1,133 ms |
| 0.2 | 17/25 | 23/25 | 20/20 | 5 | 0.009342 | 1,183 ms |
| 0.3 | 8/25 | 23/25 | 20/20 | 5 | 0.007462 | 1,150 ms |
| 0.4 | 6/25 | 23/25 | 20/20 | 5 | 0.006936 | 1,174 ms |
| 0.5 | 5/25 | 23/25 | 20/20 | 5 | 0.006718 | 1,150 ms |
| 0.6 | 4/25 | 24/25 | 21/21 | 4 | 0.006474 | 1,150 ms |
| 0.7 | 2/25 | 24/25 | 21/21 | 4 | 0.006006 | 1,150 ms |
| 0.8+ (always small) | 0/25 | **24/25** | 21/21 | 4 | **0.005503** | 1,106 ms |

Supplement (7 known small-model failures): correct 1/7 at every threshold (q109 on both tiers).

**Judged results.**

**q051: the larger model turned no answer into a wrong one.** The small model ran out of tokens and returned
nothing; the large model returned a confident, cited, wrong date for when Acme's hosting contract ends ("30
November 2026"; the agreement ends 31 December 2026). **In a system sold on trustworthy citations, a wrong
answer is worse than no answer.** The upgrade that was supposed to help the hardest question made it worse.

- **N = 0. *Needs large* is empty on both sets.** Subset: small tier correct 24/25, large tier 22/25. q051 (above)
  was the only supplement candidate. q029 is wrong on both tiers (the known neighbouring-date retrieval miss);
  q109 is correct on both.
- **Small better: q074 and q005.** q074: the small tier answered correctly, the large tier refused. q005: both
  tiers give the same dates and both omit the auditor (Nordcert); the judge passed the small answer and
  failed the large one for that omission, which is judge inconsistency on identical substance (the second
  field data point, after q054). The large answer's extra stacked `[S6]` citation is genuinely unsupported.
  Counted strictly, always-small leads always-large by 2 items; setting q005 aside, by 1 (q074).
- **Underperform verdict, read off the committed table: not underperform.** *Needs large* is empty, so the
  heuristics have nothing to miss, and an LLM classifier is not justified by this data.
- **Acceptable-delta check** (pre-registered: routed correctness and faithfulness within 1 item of always-large
  on the subset): **passes.** Routing off (always small) is 24/25 correct against always-large's 22/25 (2 items
  better, not worse) and 100% faithful against 100% (21/21 vs 20/20). Every threshold in the sweep is within
  the delta, and none is better than routing off.

Always-large costs **1.94×** always-small; latency is a wash.

**Missed prediction, recorded as visibly as the hits:** I predicted the large tier, as a reasoning model,
would spend *more* completion tokens. It spent **fewer**: median 119 against the small tier's 135 on the
subset (264 against 380 on the supplement). The cost ratio still lands near the 2× price ratio because the
prompt (median ~2,370 tokens, identical on both tiers) dominates cost either way.

**Underperform verdict, committed for every branch before the judge runs.** The pre-registered test: *needs
large* is non-empty and no threshold sending at most half the traffic catches at least half of it. Complexity
scores: q051 0.6175 (multi-hop); q029 0.2717 and q109 0.2511 (single-hop, typical of easy questions).

| *Needs large* turns out to be | Verdict |
|---|---|
| empty, or {q051} | not underperform: thresholds 0.3-0.6 catch q051 sending ≤ 25% of the 32 items to large |
| {q051, q029} or {q051, q109} | not underperform: catching q051 alone is half |
| {q051, q029, q109}, {q029}, {q109} or {q029, q109} | underperform: catching q029/q109 needs threshold 0.2, sending 75% to large |

**Claim to ship once judged** (user-approved shape; N filled in from the judging):

> **Complexity routing: built and measured; on this corpus it adds cost, not quality.** The heuristic
> classifier separates question complexity well (multi-hop questions average 0.66, single-hop 0.22), but
> answer quality here is bounded by retrieval, not by the generator. On the 25-item subset the small model
> fails one question and the large model fails it too, because the fact it needs is not in the six chunks
> either model sees. Sending any share of traffic to the large model raised shadow cost by up to 1.94× with
> no measured quality gain on the subset, and no item gained among seven known small-model failures. On
> the subset the large model was worse (22/25 correct against 24/25), and on the hardest failure it replaced
> a non-answer with a confident wrong date: in a system sold on trustworthy citations, a wrong answer is
> worse than no answer.
> **The router is built, tested and configurable; it is disabled by default because the measurement showed
> it costs money without improving answers on this corpus.** Revisit after Phase 5: hybrid retrieval changes
> what reaches the generator, and only then could a larger model have something to fix.
>
> The transferable lesson: a complexity router only pays off when the generator is the bottleneck. Measure
> which stage is binding before building one.

## Phase 4 gate: plan and predictions (fixed 2026-10-30, before Run A)

Gate items (spec §5): (1) cache hit rate on a realistic repeated-query workload; (2) near-miss pairs still
produce different answers; (3) faithfulness with routing enabled within an acceptable delta of always-large,
stated as a number; (4) cost and p95 latency deltas vs the Phase 2 baseline. Added by the user, 2026-10-31:
**(5) the isolation suites run green on a quiet machine before the gate closes**: `tests/test_acl_isolation.py`,
`tests/test_admin_isolation.py` and `tests/test_cache_isolation.py`, run in full with nothing else running.
They are the security proof; "no relevant code changed" is the assumption that lets a regression through, so
this item is never satisfied by inference.

**Item 2 is already covered** and is cited, not re-run: the cache isolation suite (all five near-miss pairs at
every sweep threshold, 98/98 at 0.88 and at 0.99, and at all nine thresholds in the sweep) and the cache sweep
(no hit served another item's answer at any threshold).

**Run A: the Phase 4 baseline.** `run_eval.py --baseline "Phase 4" --clear-cache`: all 100 golden items,
shipped configuration (cache on at 0.95, routing off), single pass, judge-v2, planned across sessions by the
budget day plan. Compared with Phase 3 only. Predictions:
- **Cache hits: exactly 0.** All 100 questions have distinct (tenant, content key) pairs and the cache starts
  empty, so no request can hit. Any hit is a cache bug.
- **Retrieval metrics identical to Phase 3.** Same corpus, chunker, embedder, ACL and top-k; the cache never
  touches retrieval. Any difference is a bug.
- **Correctness unchanged within judge and generation noise: |Δ| ≤ 3 items** against Phase 3's 77/85 correct
  answerable. Unanswerable refusals stay 15/15, with no hallucination. Known movement: the completion limit
  is now 1000 (was 700), so Phase 3's q052 truncation becomes a genuine refusal; q051 truncated once at 1000 on
  2026-10-29 and may again. **A larger correctness move means something is wrong with the cache, not that it
  improved anything.**
- **Latency: about +1 ms p50 on every query** (the miss-path lookup, measured at p50 1 ms in the sweep);
  totals are dominated by the model and this machine's noise.
- **Item 3 from Run A:** the shipped configuration's faithfulness on all 100 items. The always-large comparison
  exists on the 25-item subset only (routing off was 24/25 correct vs 22/25, faithfulness 100% vs 100%); a
  full-set always-large run would cost about a day of the large model's budget and is not part of this plan.
  **Gap accepted by the user, 2026-10-31, and closed: not to be revisited.** The subset settled it (routing off 2
  items better) and the mechanism explains why: answer quality is bounded by retrieval, not the generator.
- **Item 4 from Run A:** cost per query (shadow cost at the list prices, recomputed for Phase 2 from its logged
  tokens) and p95 latency, each against the Phase 2 baseline run. Expected: cost per query within ±10% (same
  model, same six-chunk prompt); no latency direction predicted beyond the ~1 ms lookup.

**Run B: realistic repeat workload** (`eval/repeat_workload.py`, `eval/repeat_workload.jsonl` committed with
this section). 250 requests over the 100 items, Zipf-shaped (item at popularity rank r asked ⌈40 / r⌉ times:
61 items asked once, the most popular 40 times), shuffled, each request by the item's own user, exact question
text, cache cleared at the start. No LLM calls: misses replay Run A's real answers, so what a miss costs is
that item's Run A shadow cost and model latency. Predictions:
- **Hits = Σ (asks − 1) over cacheable items**, exactly: every repeat of a stored answer hits within the 24 h
  TTL; bypassed, refused and truncated items never hit. With Phase 3's outcomes standing in for Run A's, that
  is 138 of 250 (55.2%); the exact figure is fixed by Run A's outcomes before Run B runs.
- p50 latency: hits about 25 ms; misses about 27 ms plus the model (~1.1 s p50).
- Shadow cost saved: the hit requests' share of the no-cache cost, close to the hit rate (per-query costs are
  similar).

**Run B prediction, fixed from Run A's outcomes (2026-11-01, before Run B runs):** Run A answered 80 items; minus
q056 and q074 (bypassed), **78 are cacheable**. Predicted **hits = 143 of 250 requests (57.2%)**, exactly. The
repeated items that can never hit: q054 (truncated); q066, q078, q084, q087, q106 (refused). Predicted shadow cost:
**USD 0.054004 without the cache, USD 0.029641 saved (54.9%)**, each miss costed at its item's Run A cost. Any
other hit count means the cache is not doing what it is specified to do.

## Golden set baseline — Phase 4

Full run of all 100 golden-set items, 2026-11-01T10:16:51+00:00, by `uv run python eval/run_eval.py --baseline "Phase 4"`. Results: `eval/baselines/phase-4.json`.

- Generator: `openai/gpt-oss-20b` (tier `small`), prompt `answer-v2`; judge: `openai/gpt-oss-120b` (tier `large`), prompt `judge-v2`
- Retrieval: vector-only, ACL-filtered in SQL as each item's seeded `as_user`; answers use top 6; metrics at top 10
- Golden set hash `d58769e8532dd8e0`; corpus 251 chunks; commits `93811d2`, `93811d2-dirty`

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
| Refused answerable (false refusals; truncations excluded) | 4.8% | 4 / 84 |
| Truncated at the completion limit (neither answered nor refused) | 1.0% | 1 / 100 |
| Faithful (judge, answered items) | 98.8% | 79 / 80 |
| Relevant (judge, answered items) | 100.0% | 80 / 80 |
| Citations supported (judge-v2, answered items) | 92.5% | 74 / 80 |
| Correct (judge; refusals and truncations count as not correct) | 88.2% | 75 / 85 |
| Near-miss pairs with both answers correct | 100.0% | 5 / 5 |

Judge errors: 0. Hallucinated on unanswerable: none. Refused answerable: ['q106', 'q052', 'q064', 'q066']. Truncated: ['q054'].

### Phase 4 Run A against its pre-registration (completed 2026-11-01)

Two sessions (2026-10-30: 47 items, stopped by the budget day plan; 2026-11-01: 53 items). Day 2 records
commit `93811d2-dirty` because the progress-line display was fixed in the working tree while the run was in
flight; the running process had already loaded `93811d2`, which is the code that ran.

- **Held: cache hits exactly 0.** 98 queries consulted the cache (q056 and q074 bypassed), 0 hits; the cache
  held 0 live entries at the start.
- **Held: retrieval identical to Phase 3,** for every item, not only in aggregate: all 100 top-10 rankings match.
- **Held: correctness within 3 items.** 75/85 correct against Phase 3's 77/85 (Δ −2). Lost: q043 and q069
  (each omits a qualifier the reference includes: judge-v2's known strictness) and q054 (truncated at the
  1,000-token limit; answered in Phase 3). Gained: q109. Unanswerable refusals 15/15, no hallucination; near-miss
  pairs 5/5. None of these touches the cache: it answered nothing, and retrieval is identical.
- **New behaviour, not a correctness change:** q051 and q058 moved from refusing to **partial answers**: each
  answers the hop it can see and says the other is not in the sources. Neither is correct in either phase. q051's
  partial answer cites a chunk for "the sources give no end date" that does not support it: the run's one
  unfaithful answer (faithful 79/80). The completion limit rose from 700 to 1,000 tokens between Phase 3 and
  Phase 4; whether that extra room is what turns refusals into partial answers is not established.
- **Missed, slightly: lookup cost.** Predicted ~1 ms p50 from the sweep; measured **2 ms p50, 4 ms p95** on the
  miss path. Still negligible beside the model.
- **Item 3 (faithfulness, shipped configuration, 100 items): 79/80 faithful (98.75%), 80/80 relevant,
  citations supported 74/80 (92.5%).** The always-large comparison is the subset's (routing off 2 items better);
  the full-set gap was accepted and closed.
- **Item 4 vs the Phase 2 baseline run** (each run's own `query_log` rows; Phase 2 cost recomputed from its
  logged tokens at the same list prices):

| | Phase 2 | Phase 4 | Delta |
|---|---|---|---|
| Shadow cost per query | USD 0.000238 | USD 0.000226 | **−5.1%** (within the predicted ±10%) |
| Total latency p95 | 2,701 ms | 1,688 ms | **−1,013 ms** |
| Total latency p50 | 1,245 ms | 847 ms | −398 ms |
| Model latency p95 | 2,577 ms | 1,641 ms | −936 ms |
| Retrieval p50 / p95 | 38 / 291 ms | 31 / 69 ms | |
| Prompt tokens p50 | 2,434 | 2,380 | |

  **The latency drop is the model's, not the cache's**: Run A had no hits, and the p95 fall is almost entirely
  model time (Groq-side variance between runs a week apart), so it is not a Phase 4 gain and is not claimed as
  one. The small cost drop follows the slightly shorter prompts since Phase 3's ACL filtering. The logged shadow
  cost (`query_log.est_cost_usd`) matches the recomputed figure exactly (USD 0.022596 for the 100 queries).

## Phase 4 gate: results (2026-11-01; awaiting user approval)

| Gate item | Evidence | Result |
|---|---|---|
| 1. Cache hit rate on a realistic repeated-query workload | Run B (`eval/gate_phase4/run_b.json`): 250 Zipf-shaped requests over the 100 items, exact repeats, cache cleared at the start | **143/250 hits (57.2%), exactly as predicted from Run A.** Hit p50 19 ms vs miss 21 ms plus the model (Run A model p50 806 ms). Shadow cost USD 0.054004 → 0.024363: **USD 0.029641 saved (54.9%)**, exactly as predicted. Paraphrased traffic would not hit (cache sweep: 0/25 at every threshold, the stated cost of the word check). |
| 2. Near-miss pairs still produce different answers | Cited, not re-run: cache isolation suite (all five pairs at all nine sweep thresholds); cache sweep (no hit served another item's answer at any threshold); and Run A (near-miss pairs both correct 5/5) | **Pass** |
| 3. Faithfulness with routing enabled within an acceptable delta of always-large | Routing ships **off** (measured decision). Shipped configuration on all 100 items (Run A): faithful 79/80 (98.75%). Always-large vs routing off on the 25-item subset: correct 22/25 vs 24/25, faithful 20/20 vs 21/21 | **Delta: routing off is 2 items more correct and 0 points less faithful than always-large** (subset); within the pre-registered 1-item delta. The full-set always-large comparison was not run (gap accepted and closed). |
| 4. Cost and p95 latency deltas vs the Phase 2 baseline | Run A vs the Phase 2 run, each from its own `query_log` rows | **Cost per query −5.1%** (USD 0.000226 vs 0.000238). **p95 latency −1,013 ms** (1,688 vs 2,701 ms), which is model-side variance between runs a week apart, not the cache (Run A had 0 hits): not claimed as a gain. |
| 5. Isolation suites green on a quiet machine (added by the user) | `tests/test_acl_isolation.py`, `tests/test_admin_isolation.py`, `tests/test_cache_isolation.py`, run together in full at `356d433`, nothing else running from this project, 7.8 GB machine | **249/249 passed** (124 + 27 + 98), 1 min 57 s, peak 803 MB. Full suite 452/452 and smoke pass on the same commit. |

**Phase 3 → Phase 4, with the caveats applied.** Both baselines use judge-v2, so judge-scored numbers are
comparable this time.

| | Phase 3 | Phase 4 | Reading |
|---|---|---|---|
| Retrieval (recall@6 / MRR / all-hops@10) | 86.5% / 0.700 / 87.1% | identical, all 100 rankings | The cache never touches retrieval. |
| Correct (answerable) | 77/85 | 75/85 | Δ −2, inside the pre-registered ±3 noise band; not a cache effect (0 hits). |
| Faithful (answered) | 79/79 | 79/80 | One unfaithful partial answer (q051). |
| Citations supported | 74/79 | 74/80 | |
| Refused answerable / truncated | 5 / 1 | 4 / 1 | q051 and q058 now give partial answers instead of refusing; q054 truncated instead of q052. |
| Unanswerable refused | 15/15 | 15/15 | |
| Cost per query (shadow) | USD 0.000224 | USD 0.000226 | Flat. |
| p95 latency | 2,674 ms | 1,688 ms | Model-side variance, not a Phase 4 effect. |

**What Phase 4 adds, stated plainly:** a permission-scoped semantic cache that, on repeated traffic shaped like
real use, served 57% of requests in ~19 ms and cut shadow cost by 55%, while changing no answer, adding ~2 ms to
every miss, and passing every isolation probe. Paraphrased questions do not hit, by design. Complexity routing is
built, tested and off by default, because on this corpus it costs money without improving answers.

## Phase 5 (GraphRAG + hybrid retrieval): pre-registration (fixed 2026-11-01, before any Phase 5 code)

**Baseline: Phase 4** (`eval/baselines/phase-4.json`) for every comparison, the standing rule. The spec's gate
asks for multi-hop accuracy against Phase 2; both numbers are reported, but Phase 2 predates the ACL shift and
used judge-v1, so the judgement is against Phase 4.

### What is actually gainable now

- **Buried-fact recall@6: 18/20; at most 2 gainable** (q023, gold not in the top 10; q106, gold at rank 10). A
  correction to the earlier framing: the original ceiling note allowed 3 gainable items from Phase 2's 17/20, and
  Phase 3's ACL shrinkage took **one** (17 → 18), not two. Both remaining items have the same gold chunk
  (`hr-leave-policy#1`, a large mixed-topic chunk) and both questions share rare words with it ("Hajj";
  "maternity", "reduced hours", "returning"), which is the shape keyword search can help.
- **Multi-hop all-hops@10: 15/25; 10 gainable**, in two structural groups (missing hop's gold chunk compared with
  the question's distinctive words, no search run):
  - *Lexical* (the missing hop shares distinctive words with the question): q067 (Tessera, notice), q068 (ACCA,
    exam, study leave, sitting), q070 (Ledger Vault, audit working papers, contract end), q073 (Tessera, resize,
    storage, March 2026 outage), q075 (Tessera, Service Credit, availability, March 2026).
  - *Bridge* (the missing hop shares only generic words; it connects through an entity named in the hop already
    found): q051 (Cobalt Cloud), q056 (the failover runbook setting), q058 (the Brightwater engagement lead's
    practice), q064 (Tessera Cloud's commitment), q069 (Sunridge data return → the ISO surveillance plan).
  - Also reported: **all-hops@6 11/25**, what the model actually sees; q052, q060, q063 and q066 pass @10 but not @6.
- **Multi-hop correctness: 18/25** (Phase 4, judge-v2), higher than all-hops@6 (11/25): the model sometimes answers
  from evidence outside the labelled gold chunks, so retrieval gains will not map one-to-one onto correctness.
  Phase 2's 18/25 was judge-v1 and is not comparable.
- **Single-hop: recall@6 46/50, correct 47/50.**
- **q022 is no longer a Phase 5 test.** The EVAL_RESULTS criterion (on-call chunk in its top 6, answered with a
  valid citation) has been met since Phase 3's ACL filtering (rank 5, correct in Phase 3 and Phase 4). It becomes
  a regression check: it must stay in the top 6.

### Measurement plan: two mechanisms, two measurements

- **M1, hybrid:** vector + Postgres FTS, fused with Reciprocal Rank Fusion. Constants fixed here, not tuned on the
  golden set: RRF k = 60, each path contributes its top 20, the model still sees the fused top 6.
- **M2, hybrid + graph:** M1 plus the graph path as a third RRF input.
- Each is measured by a full 100-item `run_eval.py --retrieval-only` run (no LLM calls, so attribution costs
  nothing): M1 against Phase 4, M2 against M1. The gate is one full judged run of the final configuration
  (two-day budget), cache cleared at its start.
- The optional cross-encoder rerank (spec task 5) is not planned.

### Predicted deltas (modest by intent)

**M1, hybrid, against Phase 4:**
- Buried-fact recall@6: **+1** (19/20); range 0 to +2. The two items share one gold chunk and may move together.
- Multi-hop all-hops@10: **+2** (17/25); range +1 to +4, from the lexical group only; the bridge group unchanged.
  all-hops@6: +1 to +3.
- Single-hop recall@6: no loss beyond 1 item (≥ 45/50). A larger drop means fusion is demoting correct vector hits.
- q022 stays in the top 6.

**M2, graph, against M1:**
- Multi-hop all-hops@10: **+1**; range 0 to +2, from the bridge group only. It depends on a small free model
  extracting the bridging entities and relations correctly; if the graph adds nothing, that is reported as plainly
  as routing was.
- Buried-fact and single-hop: no change (± 1).

**Gate run, against Phase 4:** multi-hop correct 18/25 → +1 to +3; single-hop correct no regression beyond the
±3-item noise band seen in Run A.

### Constraints fixed before design

- **Every path filters ACLs in SQL** (invariant 1): the FTS query uses `acl_predicate`; the graph walk applies the
  predicate to **every relation it traverses** (through that relation's provenance chunk), not only to the final
  chunks. The spec's §4.3 query applies it only at the end, which would reveal that an entity exists through a
  restricted relation; correction L forbids that. The walk goes both directions at each step (correction M), depth
  capped at 2.
- The entity-leak probes (a033-a038) and all other adversarial probes run against every path automatically (P1),
  and the structural test that every chunks query carries the predicate extends to the FTS and graph SQL.
- **Extraction:** small tier, structured JSON, the spec's six entity types, per chunk with provenance. 251 chunks at
  roughly 1.5-2k tokens each is 375-500k generator tokens, two to three days of budget, so extraction is resumable
  per chunk; extraction cost and ingestion time per document are recorded (a gate item).
- Retrieval changes do not wipe cached answers (the triggers fire on chunk and document writes only), so every
  measurement run clears the cache first.

### Addendum (user-approved, fixed 2026-11-01 before any Phase 5 measurement)

- **Spec defect recorded** as CLAUDE.md correction T (the §4.3 graph query filters only the final chunks).
- **Extraction provenance:** every extraction run records its model ID and prompt version beside the cost and
  ingestion time per document, so a later re-extraction is comparable.
- **M1 keyword path, configuration fixed here:** Postgres FTS with the `english` configuration over the chunk's
  heading path and content; the query is the OR of the question's lexemes (an AND of every word would match almost
  nothing for full-sentence questions); ranked by `ts_rank_cd` with no length normalisation; ACL predicate in the
  WHERE clause. Each keyword hit also carries its cosine similarity, so the routing classifier's retrieval features
  keep reading cosines rather than RRF scores.
- **Query planner (spec task 6), decision rule fixed before measuring:** two variants of M2 are measured, *always
  fuse* (the graph path is an RRF input on every query) and *gated* (the graph path joins only when the complexity
  score is ≥ 0.38, the gap between the highest single-hop score, 0.369, and the lowest multi-hop score, 0.390, in
  the score distribution measured on 2026-10-29 with no outcomes involved). **Choose gated unless always-fuse
  catches at least 2 more multi-hop items (all-hops@10) than gated**, because gating spares the graph cost on the
  75% of traffic that is not multi-hop.
- **Single-hop regression accepted from always-fuse: at most 1 item** of single-hop recall@6 below M1 (and no loss
  on the buried-fact class). Beyond that, always-fuse is rejected whatever it gains on multi-hop: displacing good
  vector hits on simple questions is a cost the rule does not trade.

### M1 (hybrid: vector + FTS, RRF) measured 2026-11-01

Full 100-item `run_eval.py --retrieval-only` with `RETRIEVAL_MODE=hybrid` at `cf593c6` (RRF k = 60, top 20 per
path; `eval/phase5/m1_hybrid.json`), compared item by item with the Phase 4 baseline. No LLM calls. (The
harness's own comparison line points at the last retrieval-only run, Phase 2's unfiltered one from 2026-10-23,
which is not the comparator.)

| Measure | Phase 4 | M1 | Predicted | |
|---|---|---|---|---|
| Buried-fact recall@6 | 18/20 | **20/20** | +1 (range 0 to +2) | held, top of range |
| Multi-hop all-hops@10 | 15/25 | **17/25** | **+2** (range +1 to +4) | **held exactly** |
| … lexical group | 0/5 | **2/5** | gains here only | held |
| … bridge group | 0/5 | **0/5** | unchanged | held |
| Multi-hop all-hops@6 | 11/25 | **14/25** | +1 to +3 | held, top of range |
| Single-hop recall@6 | 46/50 | **49/50** | no loss beyond 1 | held: 0 lost, 3 gained |
| q022 (regression check) | rank 5 | rank 3 | stays in the top 6 | held |

- **The theory held where it could have failed:** both multi-hop gains are lexical-group items (q067 hop 0:
  not in the top 10 → rank 7; q068 hop 1: → rank 8), and no bridge-group item moved into the top 10. A gain in the
  bridge group would have falsified the lexical/bridge account; none came. The other three lexical items stayed
  out (q070, q073, q075), so FTS lifted 2 of 5 candidates.
- **Buried facts:** q023 (not in the top 10 → rank 4) and q106 (rank 10 → 5), the two predicted candidates sharing
  one gold chunk, moved together, as noted in the pre-registration.
- **Single-hop gained 3 and lost none at recall@6:** q023 and q106 (above) and q032, which was not predicted.
- **all-hops@6 gains came from items already passing @10** (q060 7 → 3, q063 7/5 → 5/2, q066 8 → 2), so the model now
  sees both hops for them; q067 and q068 reached the top 10 but not the top 6.
- **What got worse:** **q029's gold chunk fell out of the top 10** (rank 9 → beyond 10): a single-hop loss at @10, not
  at @6, on an item already answered wrongly (the neighbouring-date retrieval miss). Smaller shifts that stayed inside
  the top 6: q074 hop 1 (2 → 5), q012 (2 → 3), q104 and q110 (1 → 2/3), several multi-hop hops by one place; q052 hop 1
  7 → 8 and q075 hop 0 5 → 6.

### M2 feasibility probe: pre-registration (fixed 2026-11-01, before any extraction)

M2's whole remaining target is the bridge group: buried-fact is closed at 20/20 and the lexical group has been
measured. Before extracting the full corpus (251 chunks, two to three days of generator budget), a graph is built
over a subset and the bridge items are measured against it. **This is a feasibility probe, not the M2
measurement.**

- **Subset** (`eval/phase5/graph_probe_subset.json`, committed with this section): **54 chunks**, the gold chunks of
  both hops of q051, q056, q058, q064 and q069 (10) plus every chunk M1 retrieves in the top 10 for those five
  questions (44 distractors the graph path must walk past). Whole gold documents were the first definition
  considered; they come to 125 chunks (the contracts and post-mortems run to 14-19 chunks), which is no longer a
  probe, so the subset was narrowed to the chunks these questions actually touch.
- **"Resolves":** the item reaches all-hops@10 (both hops in the top 10) with the graph path fused into M1. All
  five score above the planner's gate threshold (0.62-0.72 against 0.38), so gated and always-fuse coincide for
  them; the planner choice is not tested here. all-hops@6 is reported too.
- **Decision rule:** **2 or more** of the 5 resolve → extract the full corpus and run the real M2 measurement (with
  the planner comparison and the single-hop limit already fixed). **0** → do not extract; report "the graph layer
  did not help on this corpus" the way routing was reported, with the limitation below. **Exactly 1** → below the
  bar, so no full extraction by default; reported with the item named, and brought to the user to decide.
- **Limitation, stated in advance:** the subset omits most of the corpus. The full graph could connect paths the
  subset cannot see, so a 0 on the subset is weaker evidence than a 0 on the full corpus; the omitted chunks could
  also add distracting paths, so a probe success can overstate full-corpus success, which is why 2 or more leads
  to the full measurement rather than to a claim.
- **Extraction and graph, fixed for the probe:** small tier (`openai/gpt-oss-20b`), prompt `extract-v1`, structured
  JSON, the spec's six entity types (PERSON, ORG, CONTRACT, POLICY, DATE, PRODUCT), relation labels as short verb
  phrases, one call per chunk with provenance; model ID, prompt version, tokens and time per chunk recorded.
  Entity resolution by normalised name within a tenant (the spec's embedding-similarity and alias steps are not
  needed to test feasibility and are not built for the probe). Graph path: seed entities are those extracted from
  M1's fused top 6; the walk goes both directions, depth at most 2, and every traversed relation must have a
  provenance chunk the caller may read (correction T); candidates are the provenance chunks reached, ordered by
  depth then by number of supporting relations, top 20 into RRF as a third list (k = 60).

### M2 probe: deviation from the pre-registered extraction setup (recorded 2026-11-02, before further extraction)

**What happened.** The first three probe chunks (eng-postmortem-2026-03-atlas-outage #0, #11, #13) all ended
`truncated` at the pre-registered 2,000-token completion limit (prompt 498-616 tokens, completion 2,000 each,
about 7.7k tokens spent, no relations stored). Extraction was stopped rather than adjusted silently.

**Diagnostic, one call** (`eval/extract_diag.py`, log `~/gateway_runs/extract_diag_20261102.log`, logged in
`graph_extraction` as `extract-v1-diag`): chunk #0, same model, prompt and temperature (0.0), limit 8,000.

| finish | prompt | completion | of which reasoning | of which content | content parses |
|---|---|---|---|---|---|
| stop | 498 | 1,351 | **1,079 (80%)** | 272 (1,091 chars) | 9 entities, 8 relations |

**Finding, worth stating on its own:** on a reasoning model (gpt-oss-20b on Groq), **the reasoning tokens are
counted inside `completion_tokens` and consumed the completion budget**; the JSON itself is small (~270 tokens).
Reasoning length also varies between calls at temperature 0: the same chunk ran past 2,000 tokens on 2026-11-01
and finished at 1,351 here, so a limit that fits one call does not reliably fit the next. Anyone building
extraction on a reasoning model should budget for reasoning, not for the output schema.

**Decision, by the rule fixed with the user before the diagnostic** (reasoning dominates and the JSON is small →
lower the reasoning effort at the same limit; JSON large → raise the limit; both large → fewer entity types or
split chunks): **`reasoning_effort="low"` on extraction calls, completion limit unchanged at 2,000.** Groq documents
`reasoning_effort` (`low`/`medium`/`high`) for GPT-OSS 20B and 120B (console.groq.com/docs/reasoning, read
2026-11-02); the installed openai SDK (3.35.1, `AsyncCompletions.create`) accepts the parameter.

- The prompt text is unchanged; the setup is recorded as prompt version **`extract-v1-low`** (extract-v1 text,
  reasoning effort low) so no row is confused with the pre-registered setup. The three truncated chunks have no
  `ok` row and are re-extracted under it.
- Everything else in the pre-registration (model, entity types, resolution, graph path, decision rule,
  limitation) stands.
- **Stop rule for the new setup:** if any of the first five chunks truncates or fails to parse, extraction stops
  and the result comes back for a decision; it is not adjusted again in place.
- **Retries (user-approved 2026-11-02):** a chunk that fails gets exactly one retry. JSON validity is reported
  for first attempts and after the retry separately.
- **Implementation defect, fixed 2026-11-02:** `graph_probe.py` first counted "the first five" per run, so on the
  resumed run it stopped on a failed *retry* (brightwater-health #4, attempt 33 of the setup), not on one of the
  setup's first five attempts (all five were `ok`). The counter now counts the setup's attempts across runs, as
  written above; the rule itself is unchanged.
- Low reasoning effort may extract fewer or worse relations than the default. That is a cost of this deviation:
  if the probe returns 0, the write-up names reduced reasoning as a second reason (beside the partial corpus) why
  the 0 is weaker evidence.

### M2 feasibility probe: result (measured 2026-11-02)

**Extraction** (`extract-v1-low`, gpt-oss-20b, completion limit 2,000; `~/gateway_runs/graph_probe_report_20261102c.log`):
53 of 54 subset chunks in the graph, 192 entities, 289 relations, 68,978 tokens over 56 attempts (shadow cost about
$0.015), no truncations.

| JSON validity | ok | invalid_json | rate |
|---|---|---|---|
| first attempt (54 chunks) | 52 | 2 | **96.3%** |
| after one retry (54 chunks) | 53 | 1 | **98.1%** |

The two first-attempt failures were legal-sow-brightwater-health #14 (retry ok) and #4 (retry invalid; not in
the graph). #4 is a q058 distractor, not a gold chunk; q058's gold chunks (brightwater #5, public-company-overview
#0) were both extracted.

**Measurement:** retrieval-only, `RETRIEVAL_MODE=hybrid_graph`, compared with M1 (`eval/phase5/m1_hybrid.json`);
result `eval/phase5/m2_probe.json`, log `~/gateway_runs/m2_probe_measure_20261102.log`.

| bridge item | M1 hop ranks | probe hop ranks | all-hops@10 | all-hops@6 |
|---|---|---|---|---|
| q051 | 1, — | 2, — | no | no |
| q056 | 1, — | 1, 8 | **yes** | no |
| q058 | 1, — | 1, 10 | **yes** | no |
| q064 | 1, — | 3, 10 | **yes** | no |
| q069 | 7, — | 7, — | no | no |

**Decision rule: 3 of 5 resolve (q056, q058, q064), so the rule says extract the full corpus and run the real M2
measurement.** The resolved second hops arrive at ranks 8, 10 and 10, just inside the bar; none reaches the top 6
the model sees.

**Recorded with the same prominence: the graph path, fused at equal RRF weight, damaged the top of the ranking.**

| measure | M1 | probe |
|---|---|---|
| multi-hop all-hops@10 | 17/25 | 20/25 (gained q056, q058, q064, q075; lost q074) |
| multi-hop all-hops@6 | 14/25 | **11/25** |
| single-hop recall@6 | 0.980 | **0.920** (q008 rank 1→9, q105 2→10, q111 1→10) |
| buried-fact recall@6 | 20/20 | **18/20** (q105, q111) |
| all-answerable MRR | 0.820 | **0.597** |

On the probe graph this breaks the pre-registered always-fuse single-hop limit (at most 1 item, no buried-fact
loss) three times over. Part of it is a subset artifact: chunks outside the subset have no relations, so they can
never appear in the graph list, and extracted neighbours that appear in all three lists outrank them (q111's gold
chunk, sunridge-schools #2, is not in the subset and fell from rank 1 to 10). Part may be structural: the graph list
is ordered by depth and support, not by relevance to the question, and gets the same RRF weight as the two
query-ranked lists. The full-corpus measurement separates the two; changing the graph list's ordering or weight
would be a new deviation, pre-registered before it is measured.

**Primary finding of the probe (user-worded, recorded 2026-11-02 before the full measurement):** the graph path
surfaced 3 bridge items into the top 10 while pushing all-hops@6 down from 14/25 to 11/25 and MRR from 0.820 to
0.597. The second hops landed at ranks 8, 10 and 10: inside the measured window, outside the six chunks the model
reads. **A gain that does not reach the generator is not a gain.** It is the routing lesson from the other
direction: measure the stage that binds.

### M2 full measurement: reporting and planner expectations (fixed 2026-11-02, before the full measurement)

- **Headline multi-hop number: all-hops@6** (what the generator sees), against M1's 14/25 and Phase 4's 11/25.
  all-hops@10 is reported as a diagnostic only. This supersedes the earlier framing that put @10 first (user
  decision, made after the probe and before any full-corpus number exists). The planner decision rule above keeps
  its pre-registered measure (all-hops@10) so it is not re-cut after a result was seen; its outcome is reported
  beside the @6 numbers for both variants.
- **Planner expectation, quantified from the classifier alone (no retrieval outcomes):** on the 2026-10-29 score
  distribution the highest single-hop score is 0.369 and the lowest multi-hop score 0.390, so with the gate at
  0.38 **gated fusion should leave every single-hop and buried-fact item exactly at M1** (0 of 50 cross the gate)
  and match always-fuse on all 25 multi-hop items. If so, the decision rule picks gated (always-fuse cannot catch
  2 more multi-hop items than an identical set), and the always-fuse damage above is confined to the variant that
  is not chosen. Caveat: those scores were computed with vector retrieval; the classifier reads cosine features,
  which hybrid hits also carry, but the top-k set differs, so scores can shift. Every single-hop or buried item
  that crosses the gate under hybrid is listed by name in the result.
- **If the full corpus still shows the always-fuse damage**, a relevance-ordered graph list or a lower RRF weight
  for it are candidate fixes; either is a new deviation, brought to the user and pre-registered before it is
  built or measured.

### M2 measured on the full corpus (2026-11-03): the graph path, as built, made retrieval worse

**Extraction** (`extract-v1-low`, gpt-oss-20b, limit 2,000; `~/gateway_runs/graph_full_report_20261103.log`):
250 of 251 chunks, 697 entities, 1,147 relations, 302,667 tokens over 253 attempts, 411 s of LLM time, no
truncations. JSON validity: **first attempt 249/251 (99.2%)**, **after one retry 250/251 (99.6%)**; the one chunk
missing is legal-sow-brightwater-health #4 (a distractor).

**Measurement:** retrieval-only, compared with M1; `eval/phase5/m2_always_fuse.json` (`hybrid_graph`) and
`eval/phase5/m2_gated.json` (`hybrid_graph_gated`, gate 0.38), both at `0b4eff4`.

| measure | Phase 4 | M1 | always-fuse | gated |
|---|---|---|---|---|
| **multi-hop all-hops@6 (headline)** | 11/25 | **14/25** | **9/25** | **9/25** |
| multi-hop all-hops@10 (diagnostic) | 15/25 | 17/25 | 15/25 | 15/25 |
| bridge items resolved (@10) | 0/5 | 0/5 | 0/5 | 0/5 |
| single-hop recall@6 | 0.920 | 0.980 | **0.640** | 0.980 |
| buried-fact recall@6 | 18/20 | 20/20 | **12/20** | 20/20 |
| MRR (all answerable) | 0.700 | 0.820 | 0.523 | 0.727 |

- **Multi-hop, both variants, against M1:** gained none at @6, lost q060, q061, q065, q071, q072; at @10 lost q067
  and q071. On the headline number both variants fall below Phase 4 as well as M1. Bridge items (hop ranks):
  q051 [9, —], q056 [3, —], q058 [1, —], q064 [7, —], q069 [—, —]. **The probe's 3 resolutions did not survive
  the full graph**: the outcome the probe's limitation named in advance (a subset success can overstate
  full-corpus success).
- **Planner rule (pre-registered measure, all-hops@10): always-fuse 15, gated 15; always-fuse does not catch 2
  more, so gated is chosen.** Always-fuse is rejected independently by the single-hop limit: it lost 18 single-hop
  items at @6 (q004, q008, q018, q020, q022, q023, q026, q027, q032, q039, q040, q043, q101, q104, q106, q108,
  q109, q110), 8 of them buried-fact (q022, q023, q026, q104, q106, q108, q109, q110). q022 fell from rank 3 to 10
  under always-fuse and stays at 3 under gated.
- **Gate:** the planner expectation held. 0 of 50 single-hop and 0 of 20 buried-fact items crossed 0.38, and
  gated left all of them exactly at M1. All 25 multi-hop items crossed it. One other item crossed: **q093
  (near-miss, score 0.513)**.
- **The subset-artifact hypothesis is refuted:** on the full corpus, where every chunk can appear in the graph
  list, the damage is larger, not smaller. It is structural.

**Diagnosis (no LLM calls; `eval/phase5/graph_reach.py`, output `eval/phase5/m2_graph_reach.txt`).** For the 16
gold hops missing from M1's top 6 across the multi-hop items:
- **All 16 are reachable** in the depth-2 walk; the walk is not the problem. It reaches too much: the median
  graph list is 47 chunks. Hub entities make it so: "Acme" is attached to 50 of acme's 133 chunks, "Globex" to 45
  of globex's 118, "Cobalt Cloud" to 43.
- **The ordering is the problem.** Ordered by depth then support (as pre-registered), only 7 of the 16 make the
  top 20 that enters RRF; ordered by cosine to the question, 13 would, but **none would be in the graph list's
  top 6 by cosine**. The depth/support order promotes hub-adjacent, relation-dense chunks, which then take a
  third RRF vote and displace query-relevant chunks.

**Finding:** the graph surfaced no gain that reaches the generator and cost 5 multi-hop items at @6 even when
confined to multi-hop questions. No ordering or weight change has been made; a proposal goes to the user first.

### M2 option A: pre-registration (fixed 2026-11-03, before A is built or run; user-approved)

One final, pre-registered attempt; nothing else in M2 changes. If it fails the rule below, M2 is reported as "the
graph layer did not help on this corpus" (option D) and M1 ships.

- **The single change:** the graph list is ordered by **cosine similarity to the question** (the score the walk
  already computes) instead of depth then support. Everything else as measured: gated at 0.38, depth 2, seeds =
  entities of the fused top 6, top 20 of the graph list into RRF, k = 60, equal weight.
- **Adoption rule:** adopt gated+A only if **multi-hop all-hops@6 > 14/25 (M1)** and **no single-hop or
  buried-fact item loses recall@6 against M1**. Otherwise D. The planner variant is not revisited (gated stands).
- **Arithmetic ceiling, computed before the run** (`eval/phase5/graph_ceiling.py`, output
  `eval/phase5/m2_graph_ceiling.txt`; read-only, no LLM calls). A missing hop enters M1's top 6 only if its fused
  score, with a graph vote of 1/(60 + its cosine rank in the graph list), beats the sixth chunk's. Under the
  optimistic assumption that the chunks already in the top 6 gain nothing from the graph list:
  - 6 of the 16 missing hops can never climb: 2 are in no list at all (q070, q073: the graph cannot help a hop
    no path finds), 1 is outside the graph top 20 (q075), 3 fall short even with the vote (q051, q063, q064).
  - 10 hops can climb, covering 8 items with every missing hop climbable: q052, q056, q058, q067, q068, q069,
    q072, q074. **Ceiling: +8 items at @6.** Of the 5 bridge items only q056 and q058 are under the ceiling.
  - Correction to the arithmetic given to the user before this section: "only hops already ranked 7-20 in the
    vector or keyword list could climb" stands, but there are more of them (10 of 16) than the "0 to 1" estimate
    implied. That estimate was too low as a ceiling.
- **Why the realistic gain is far below the ceiling:** the top-6 chunks are the walk's seeds' provenance and are
  the most similar to the question, so under cosine ordering they take the graph list's top ranks, and their own
  graph vote (1/61 to 1/66) is larger than any missing hop's (1/67 or less). The ceiling assumes they get none.
- **Prediction:** multi-hop all-hops@6 **14/25, range 13-16**: the damage measured under depth/support ordering
  (14 -> 9) is largely undone because the graph list now echoes the vector ranking; gain over M1 0 to +2, most
  likely from q052, q069 or q074 (the hops whose third vote clears the sixth score by the widest margin).
  Single-hop and buried-fact: exactly at M1 (gated; 0 of 70 crossed the gate). **Most likely outcome: the rule
  is not met and D follows.**

### M2 option A: result (measured 2026-11-03 at `cb46d0e`)

`RETRIEVAL_MODE=hybrid_graph_gated GRAPH_ORDER=cosine`, retrieval-only against M1; `eval/phase5/m2_optionA.json`.

| measure | M1 | gated, depth/support | **gated, cosine (A)** | predicted for A |
|---|---|---|---|---|
| multi-hop all-hops@6 | 14/25 | 9/25 | **14/25** | 14 (13-16) |
| multi-hop all-hops@10 | 17/25 | 15/25 | 18/25 | not predicted |
| single-hop recall@6 | 0.980 | 0.980 | 0.980 | at M1 |
| buried-fact recall@6 | 20/20 | 20/20 | 20/20 | at M1 |
| MRR (all answerable) | 0.820 | 0.727 | 0.816 | not predicted |

- **Prediction held at its point value: 14/25.** Cosine ordering undid all of the damage (no item lost at @6, none
  on single-hop or buried-fact) and gained nothing at @6. The one movement is q056's second hop reaching rank 9:
  inside the measured window, outside the six chunks the model reads.
- **Adoption rule (> 14/25 with no single-hop or buried-fact loss): not met. Option D follows.** The ceiling of
  +8 assumed the chunks already in the top 6 gain nothing from the graph list; under cosine ordering they take
  its top ranks, which is why the realised gain is 0.

## Phase 5 M2 (GraphRAG): the graph layer did not help on this corpus (recorded 2026-11-03)

**Claim to ship** (user-approved shape, the routing write-up's form):

> **GraphRAG: built, measured, ACL-correct; on this corpus it does not improve what reaches the model, so it ships
> off.** Entity and relation extraction ran over all 251 chunks with the small model (99.2% valid JSON on the
> first attempt, 99.6% after one retry; 302,667 tokens, about USD 0.06 at list price). The graph walk is
> depth-capped, bidirectional, and applies the ACL predicate to every relation it traverses, not only to the
> chunks it returns (a defect in the spec's own query, corrected before any code). Fused into hybrid retrieval as
> a third RRF list, it surfaced no second hop into the six chunks the model reads. With the pre-registered
> ordering it pushed multi-hop all-hops@6 from 14/25 to 9/25 even when gated to multi-hop questions, and
> always-fused it cost 18 single-hop items. Ordered by relevance (one final pre-registered attempt) it stopped
> doing harm and still gained nothing: 14/25 against 14/25. A gain that does not reach the generator is not a
> gain.
>
> **The transferable lesson: GraphRAG's traversal reached every hop it needed — all 16 were within depth 2. It
> failed because hub entities ('Acme' on 50 of 133 chunks) make the reachable set so large that the graph list
> is near-arbitrary, and fusing it as a third equal vote damages the top of the ranking. A graph helps when
> entities are selective; on a corpus where common entities touch a third of all chunks, traversal recall is not
> the binding constraint — ranking is.**
>
> The graph code stays built, tested (the ACL-isolation suite runs in both graph modes) and off
> (`RETRIEVAL_MODE=hybrid`), as routing does. Phase 5 ships M1, hybrid retrieval, which met every pre-registered
> target.

**Evidence, by section above:** full-corpus result and diagnosis ("M2 measured on the full corpus"), reachability
and hub degrees (`eval/phase5/m2_graph_reach.txt`), option A's ceiling and result (`eval/phase5/m2_graph_ceiling.txt`,
`eval/phase5/m2_optionA.json`). The probe's 3 resolutions (`eval/phase5/m2_probe.json`) did not survive the full
graph, as the probe's pre-stated limitation allowed.

**Extraction cost and ingestion time per document (spec gate item):** `eval/phase5/m2_extraction_report.md`, one
row per document (50 documents). LLM time per document: mean 8.2 s, max 35.0 s; shadow cost per document: mean
USD 0.00115, total USD 0.0574 (Groq list price for gpt-oss-20b, read 2026-10-29; the free tier charges nothing).
Wall-clock ingestion is dominated by the 30 s pacing the free tier forces: about 33 s per chunk, so about 2.8
minutes for a 5-chunk document; with no rate limit it would be the LLM time.

## Phase 5 gate run: prediction restated for the shipped configuration (fixed 2026-11-03, before the run)

The gate run is one full judged run of `RETRIEVAL_MODE=hybrid` (M1), cache cleared at its start, compared with the
Phase 4 baseline (`eval/baselines/phase-4.json`); the Phase 2 numbers are reported beside it (spec gate wording),
judged against Phase 4.

- The pre-registered gate prediction (multi-hop correct 18/25 → +1 to +3; single-hop correct no regression beyond
  the ±3-item band of Run A) assumed M1 and M2. M2 contributes nothing to the shipped configuration and was
  predicted to contribute at most +1 at @10, so **the prediction stands unchanged** for M1 alone: retrieval-only,
  M1 raised multi-hop all-hops@6 from 11/25 to 14/25 and buried-fact recall@6 from 18/20 to 20/20, with single-hop
  recall@6 from 0.920 to 0.980.
- Correctness can lag retrieval: an item whose hops both reach the top 6 can still be answered wrongly or
  refused. Whatever the judged numbers are, they are reported against this prediction, misses as visibly as hits.
- The ACL gate item is the three isolation suites in full on a quiet machine, run after the judged run.

**Deviation recorded 2026-11-03, after session 1 and before session 2 (user decision).** Session 1 stopped on the
budget guard at 35/100. One item, **q030** (single-hop, answered), has no verdict: the judge (gpt-oss-120b,
judge-v2) ran past its 1,500-token completion limit, the same reasoning-budget effect recorded for extraction. It is
re-judged **once** at the start of session 2 (`run_eval.py --resume ... --rejudge q030`): same stored answer, the
same six sources re-read from the record's own top 6, same judge model and prompt, completion limit **4,000**.
The record carries `rejudged` (the original error and its `query_log` id); the truncated call stays in
`query_log`. If the re-judge also fails, q030 is reported as unjudged; it is not tried a third time. Any other
judge error in sessions 2-3 is reported as unjudged unless the user decides otherwise.

**Second deviation, recorded 2026-11-05 after the run completed and before the baseline was committed (user
decision).** Session 2 finished the run (100/100) with two more judge errors, **q055 and q056** (multi-hop,
answered, both correct in Phase 4): the judge ran past 1,500 tokens again. Both are re-judged **once**, exactly
as q030: same stored answers, same sources, same judge and prompt, limit 4,000. Because finalizing had deleted
the partial, it is rebuilt losslessly from the results file (`eval/reopen_result.py`) and the run is resumed
with `--rejudge q055 --rejudge q056 --compare-to eval/baselines/phase-4.json`; no item is generated again. The
uncommitted Phase 5 baseline written at the end of session 2 is replaced by the one this produces. A second
failure on either item is reported as unjudged.

## Golden set baseline — Phase 5

Full run of all 100 golden-set items, 2026-11-05T18:45:49+00:00, by `uv run python eval/run_eval.py --baseline "Phase 5"`. Results: `eval/baselines/phase-5.json`.

- Generator: `openai/gpt-oss-20b` (tier `small`), prompt `answer-v2`; judge: `openai/gpt-oss-120b` (tier `large`), prompt `judge-v2`
- Retrieval: hybrid (vector + FTS, RRF k=60, top 20 per path), ACL-filtered in SQL as each item's seeded `as_user`; answers use top 6; metrics at top 10
- Golden set hash `d58769e8532dd8e0`; corpus 251 chunks; commits `2e0fb1a`, `4dc3fd9`, `952745f`

| Retrieval (answerable items) | n | recall@5 | recall@6 | recall@10 | all-hops@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|
| all_answerable | 85 | 90.0% | 91.8% | 94.1% | 89.4% | 0.820 | 0.822 |
| single_hop | 50 | 96.0% | 98.0% | 98.0% | 98.0% | 0.782 | 0.832 |
| buried_fact | 20 | 100.0% | 100.0% | 100.0% | 100.0% | 0.756 | 0.817 |
| multi_hop | 25 | 74.0% | 76.0% | 84.0% | 68.0% | 0.862 | 0.761 |
| near_miss | 10 | 100.0% | 100.0% | 100.0% | 100.0% | 0.900 | 0.926 |

| Generation | rate | count / n |
|---|---|---|
| Refused unanswerable (hallucination guard) | 93.3% | 14 / 15 |
| Refused answerable (false refusals; truncations excluded) | 0.0% | 0 / 83 |
| Truncated at the completion limit (neither answered nor refused) | 2.0% | 2 / 100 |
| Faithful (judge, answered items) | 98.8% | 83 / 84 |
| Relevant (judge, answered items) | 97.6% | 82 / 84 |
| Citations supported (judge-v2, answered items) | 86.9% | 73 / 84 |
| Correct (judge; refusals and truncations count as not correct) | 94.1% | 80 / 85 |
| Near-miss pairs with both answers correct | 100.0% | 5 / 5 |

Judge errors: 0. Hallucinated on unanswerable: ['q090']. Refused answerable: none. Truncated: ['q051', 'q052'].

## Phase 5 headline finding: the first hallucination on an unanswerable question (q090)

**User-worded, recorded 2026-11-05 from the final Phase 5 baseline (`eval/baselines/phase-5.json`).**

Phase 5's keyword path added 3 correct single-hop answers and eliminated all 4 false refusals. It also produced the
project's first hallucination on an unanswerable question. Asked which law firm represents Globex, the system
answered with a person named as legal counsel in a related agreement, and cited a real, on-topic, permitted chunk.
q064 fails the same way: measured availability substituted for committed availability.

Two regressions, with different evidence behind them.

q064 is a clear lexical-retrieval failure: the SLA monitoring log chunk was not in Phase 4's top 6, hybrid's keyword
path brought it in, and the model answered with measured availability where the question asked for committed
availability. Word overlap does not distinguish 'measured' from 'committed'.

q090 is not. The chunk it cited was already in Phase 4's top 6 at rank 3, and Phase 4 refused. What changed is the
surrounding context: hybrid filled the six sources with Tessera agreement chunks, and with that context the model
answered instead of refusing. With a single item this cannot be separated from ordinary model variance, and the
write-up does not claim it is.

What both share is what the citation check cannot catch. It verifies that a cited chunk exists, is permitted, and
supports the claim — and in both cases all three hold. The fact retrieved is adjacent to the question rather than the
answer to it: legal counsel instead of a law firm, measured instead of committed. That class of error is invisible to
every guardrail in the system.

This is the cost of the Phase 5 gain, and it is not a bug to fix in this phase. For q064 this is a structural limit
of lexical retrieval combined with a citation-existence check; for q090 the mechanism is unestablished, but the
blindness of the citation check is the same in both. It is now measured: 1 hallucination in 15 unanswerable questions, and
citations_supported down from 0.925 to **0.869** (73 of 84 answered items; 0.878 before q055 and q056 were
re-judged, when q055's verdict marked one of its citations unsupported).

| item | question | Phase 4 | Phase 5 answer | cited |
|---|---|---|---|---|
| q090 (unanswerable) | Which law firm represents Globex in its dispute with Tessera? | refused | "Henrik Dahl, Legal Counsel." | legal-vendor-agreement-tessera-cloud #5 |
| q064 (multi-hop) | Which provider hosts Marlowe Retail Group's files, and what monthly availability does it commit to? | refused | Tessera Cloud (correct), then monthly measured availability from the SLA monitoring log, presented as the commitment | marlowe engagement letter #4, tessera-cloud #12 |

**The open question, stated rather than solved.** Whether hybrid's net effect is positive depends on how a user
weighs 3 more correct answers (and 4 fewer false refusals) against 1 confident wrong one. **For an internal document
assistant in a law firm, that trade is probably bad.** A refusal sends a lawyer to the source; a confident, cited
answer naming the wrong party is the failure a firm buys this product to avoid, and the citation makes it more
convincing, not less. Phase 5 ships what was measured: `RETRIEVAL_MODE=hybrid`, with this cost on the record. Nothing
has been changed to address it in this phase.

## Phase 5 gate: results (2026-11-06; all items evidenced, awaiting user approval)

Gate run: `eval/baselines/phase-5.json` (run `20261103T200805Z_full`, three sessions at `2e0fb1a`, `4dc3fd9`,
`952745f`; the third only re-judged q055 and q056). Judged against Phase 4; Phase 2 reported beside it.

| | Phase 2 | Phase 4 | **Phase 5** | pre-registered |
|---|---|---|---|---|
| multi-hop correct | 18/25 | 18/25 | **21/25** | 18 → +1 to +3: **held, top of range** |
| single-hop correct | 45/50 | 47/50 | **49/50** | no regression beyond ±3: **held (+2)** |
| buried-fact correct | — | 19/20 | 20/20 | — |
| unanswerable refused | 15/15 | 15/15 | **14/15** (q090) | — |
| false refusals, answerable | — | 4 | 0 | — |
| truncated generations | — | 1 | 2 (q051, q052) | — |
| faithful (answered) | — | 0.988 | 0.988 | — |
| citations supported (answered) | — | 0.925 | **0.869** | — |

- **Multi-hop, item by item (Phase 4 → 5):** q054 truncated → correct, q066 refused → correct, q069 wrong → correct;
  q051 wrong → truncated, q052 refused → truncated, q064 refused → wrong (above). q055 and q056 correct in both.
- **Single-hop:** q029, q043, q106 → correct; q005 correct → wrong.
- **Judging:** three items (q030, q055, q056) re-judged once at a 4,000-token limit after the judge's reasoning ran
  past 1,500 tokens (deviations recorded above before each re-judge); all three succeeded; 0 judge errors remain.

| Spec gate item | Evidence | Status |
|---|---|---|
| Multi-hop accuracy improves over Phase 2; report both | 18/25 (Phase 2) → 21/25; against Phase 4 also 18 → 21 | **pass** |
| Single-hop does not regress | 47/50 (Phase 4) → 49/50; 45/50 in Phase 2 | **pass** |
| Graph traversal respects ACLs (adversarial suite) | three isolation suites in full against the **real extracted graph**, quiet machine: **499/499** (section below) | **pass** |
| Extraction cost and ingestion time per document | `eval/phase5/m2_extraction_report.md` (section above) | **pass** |

The gate's quality items pass, and the Phase 5 headline finding above is the cost that comes with them.

### Isolation suites: a false pass found and closed (2026-11-05/06)

**What the first run proved, and what it did not.** The three suites ran green at `fac7afa` (495/495). Asked what
they demonstrate rather than whether they pass, the graph modes proved nothing: the test database is seeded with
the real corpus, but extraction never runs there, so it held **no entities and no relations**. In both graph modes
the graph path returned nothing, and 164 tests re-tested vector + FTS. The entity-leak probes (a033-a038), written
for the graph, had never run against an extracted graph. The suite's one mutation test (every probe leaks with the
predicate removed) ran in vector mode only, so the keyword path had never been shown live either.

**Fix (strengthens, weakens nothing):**
- `tests/fixtures/graph_extract_v1_low.json`: the graph extracted from the real corpus (697 entities, 1,147
  relations; entity names and relation labels only), exported by `scripts/export_graph_fixture.py` and keyed by
  tenant, document slug and chunk ordinal. `tests/conftest.py: load_real_graph` loads it into the test database
  (failing loudly if any provenance chunk is missing) before either graph mode runs.
- `test_each_path_is_live_and_its_predicate_has_teeth`: each path queried on its own, rule fixed before its first
  run (live: data for at least one leak probe under the real predicate; teeth: under that path's mutant, at least
  one chunk the probe's user may not read).
- `test_the_gated_mode_opens_the_graph_for_some_probe`.
- CLAUDE.md invariant 18: every isolation suite must prove its path is live.

**Result** (37 leak probes without a database setup step):

| path | returns data, real predicate | leaks under its own mutant |
|---|---|---|
| vector | 37/37 | 37/37 |
| keyword | 36/37 | 37/37 |
| graph (real graph, seeded from the hybrid top 6) | 37/37 | 37/37 |

- **Gated mode is live but thin: 3 of 37 probes open the gate (a025, a026, a027).** The entity-leak probes a033-a038
  do not reach 0.38, so in gated mode they never walk the graph. Graph ACLs on every probe are exercised by the
  always-fuse mode; the gated mode adds no path the always-fuse mode does not already test. Recorded, not fixed:
  adding probes that open the gate would be new adversarial cases, committed before any code they test.
- **Full run** at `f171263` (code; this record committed after it): `test_acl_isolation.py`, `test_admin_isolation.py` and `test_cache_isolation.py` together,
  nothing else from this project running, 7.8 GB machine: **499/499 passed** (374 + 27 + 98), 4 min 05 s, peak 805 MB.
  Full suite 742/742 and smoke pass on the same tree.

**Audit of the other paths the suites claim to cover:**
- **Cache suite: live.** Every probe fails as "not live" unless its populate request stored an entry and the stored
  answer holds the forbidden strings; mutation tests remove each key component (role signature, tenant scope, word
  check) together with the readability re-check and require the probes to fail; a separate test shows the re-check
  alone stops restricted values. It runs in the shipped retrieval mode (hybrid).
- **Admin suite: live.** A cross-tenant 404 counts only if the target's own admin can read it; a 403 counts only if
  removing the role check changes it; `same_as_missing` probes must match a random id's response exactly.
- **Keyword path:** the test database's chunks carry the generated `content_tsv`, and the path returns data for 36
  of 37 probes; it was live, but no test had shown it. It is now covered by the per-path test.
- **Vector path:** live, as before (the existing mutation test, plus the per-path test).

## Phase 6 dashboard: design and isolation probes (fixed 2026-11-06, before any dashboard code)

**Surfaces.** `GET /dashboard` is a static shell (HTML, HTMX and Chart.js from CDN, no build step) holding no data.
Every data endpoint is under `/v1/dashboard/` and requires the admin role, read from the database per request
(`require_admin`, as the admin API): `summary` (JSON: query count, outcomes, cache hit rate, modelled cost saved,
p50/p95 latency, routing distribution), `feed` (HTML fragment: recent queries), `audit` (HTML fragment: audit rows,
role filter) and `eval` (JSON: score history from the committed baselines).

**Design decisions (for user review; conservative where the spec is silent):**
1. **Tenant admins only, own tenant only.** The tenant comes from the token; no endpoint accepts a tenant parameter.
   There is no operator role, so the spec's "tenant filter" is fixed to the caller's tenant; the role filter
   narrows within it. Tenant scoping is composed from one function in `gateway/security/acl.py` so it can be mutated.
2. **No answer text and no chunk content, ever.** `query_log.answer_raw` may quote content the admin may not read
   (an admin is not HR). Retrieved chunks are shown as counts; a document title is shown only for chunks the admin
   may read under the same `acl_predicate` as retrieval, the rest counted as "restricted".
3. **Question text is shown** (the audit log's purpose: what was asked, by whom, what reached the model).
4. **Eval history is aggregates only** from `eval/baselines/phase-*.json`, never per-item questions or answers.
5. **Auth:** the bearer token is kept in `sessionStorage` and attached to every HTMX and chart request; no cookies,
   so no CSRF surface. The shell's sign-in uses the dev issuer (correction H) and says so.
6. **Cost saved is modelled:** cache hits x the tenant's mean shadow cost per answered miss in the window, labelled
   as modelled. Eval judge calls (`purpose = 'eval_judge'`) are excluded from every metric.

**Probes:** `eval/adversarial_dashboard.jsonl`, over traffic in `eval/dashboard_traffic.jsonl` (questions
across both tenants, each carrying a unique marker; HR's salary question is answered by a stub that quotes its
sources, so `answer_raw` holds the restricted figure 650,000). Categories: cross-tenant (5), tenant parameter (4),
non-admin 403 (12), unauthenticated 401 (5), restricted content (2), eval aggregates (1), stale admin (1),
markup injection (2: a question carrying a script tag must render escaped in the feed and the audit view; added
before any dashboard code). 32 probes, over 6 traffic questions.

**Pass rules (invariant 18: each probe proves its path is live):**
- Every probe: expected status; every `absent_string` absent from the response body; every `present_string` present.
- Cross-tenant and tenant-parameter probes count only if their `live_control` holds: the other tenant's admin sees
  the marker (the data exists and is visible to its owner), and the summary's all-tenant count exceeds the caller's.
- `same_as` probes must return exactly what the plain endpoint returns.
- Non-admin 403s count only if removing the admin check makes the same request not 403.
- Restricted-content probes count only if `answer_raw` really holds 650,000 for the HR query, and if, with the ACL
  predicate reduced to tenant scoping only, the withheld title "Salary Bands 2026" appears.
- The eval probe counts only if the baseline file really contains the per-item question it must not show.
- **Mutation:** with the dashboard's tenant scope replaced by TRUE, every cross-tenant probe must fail.

### Phase 6 dashboard: decision 1 revised (user, 2026-11-06, before the code change)

**Question text is shown only when the viewing admin may read every chunk that query retrieved.** Otherwise the row
is shown with everything else intact (time, user, roles, outcome, chunk counts, withheld count, denied count,
latency) and the question replaced by a marker saying why. Reason (user): question text leaks what Phase 3
protects: "minimum monthly salary for a Manager C1" tells an admin without HR access that salary bands exist and
what someone wanted from them, and in a real deployment questions are often more sensitive than documents. A
retrieved chunk that no longer exists cannot be checked, so it also redacts.

- New probes **d033** (feed) and **d034** (audit): the HR user's row is visible (`hr@acme.example`, "Question
  withheld"), its marker and wording are absent; live control: with the redaction check removed, the marker appears.
- **Probes changed to the stricter rule:** d009 and d028 had required the HR question's marker to be *present*;
  they now require the row (`hr@acme.example`, "Question withheld") present and the marker absent. This tightens
  them; nothing is removed from what they check.
- Questions from employee-level users stay visible: an admin (employee, admin; clearance 3) may read every chunk
  an employee (clearance 1) may read, so the cross-tenant probes' live controls still see their markers.
- **Rule tightened (user, option A, 2026-11-06, before the code change):** the full suite found the hole in the
  rule as first given. An employee, an engineer or a revoked HR user asking the salary question is *denied* the
  salary chunks (`denied_count` 6-8) and retrieves only public ones, which the admin may read, so the question
  showed, carrying the very phrase the rule exists to hide. The rule looks at what a query retrieved; a question's
  sensitivity is what it was aimed at, and `denied_count` is the only record of that. **A question is now also
  redacted when the ACL removed any of the asker's candidates (`denied_count > 0`).** Measured on the dev database's
  acme audit log: the first rule redacts 843 of 971 rows, the tightened rule 944 (101 more). It over-redacts where
  the admin could have read the denied chunks (their ids are not recorded). The probes are unchanged.

### Phase 6 dashboard: no question text (option C, user decision 2026-11-06, before the code change)

**Finding (user-worded):** The dashboard shows no question text. We first tried redacting questions whose retrieved
chunks the admin couldn't read, then questions where the ACL denied anything. On this corpus the second rule hid
97% of rows: everyday questions — office hours, annual leave, expense claims — have all six nearest chunks in
role-restricted documents, so almost every question is 'aimed at' restricted content. A column that is 97% withheld
and otherwise arbitrary is worse than no column. Question text belongs behind a dedicated audit-reviewer role, which
this system does not have. Recorded as a gap, not built.

- **Evidence:** `denied_count` at top 6 for an employee: 6 of 6 for "What are the standard office hours at Acme?",
  4 of 6 for "Who founded Acme Advisory Group?". A narrower signal was also measured (redact when the asker's single
  best match was denied): it still hid office hours, annual leave, expense claims and "Why was my performance review
  downgraded?", and showed only "How do I get IT help?" and "Who founded Acme?" among 9 everyday questions.
- **Implementation:** the question cell always shows "Question withheld"; `question_visible` is the one switch and
  returns False, and the text is dropped before any template sees it.
- **Probes restated (user-approved under invariant 11; no leak check removed, none made easier):** d001-d004's live
  controls move from question markers to the other tenant's user emails, which are already absent strings and must
  still leak under the tenant-scope mutation. d031-d032 become "the raw script tag never appears", the only half that
  applies when no question text renders. d009, d028, d033 and d034 are unchanged and still hold (the HR row visible
  with "Question withheld"; removing the switch shows the question).
- **Gap recorded:** an audit-reviewer role able to read question text, with its own ACL rule and probes.

### Phase 6 dashboard: result (2026-11-06; awaiting user review)

`tests/test_dashboard_isolation.py`: **44/44** at option C (34 probes, each with its live control; 9 cross-tenant
and tenant-parameter probes failing as required under the tenant-scope mutation; probe coverage). The four isolation
suites together (ACL, admin, cache, dashboard), nothing else running: **543/543**, 2 min 29 s, peak 808 MB. Full suite
793, smoke pass. (First build, before option C: 42/42 and 541/541.)

- **One probe failed on the first run, and the code was changed, not the probe:** d026 found `@acme.example` in the
  unauthenticated shell, from the sign-in form's prefilled demo identity. The prefill was removed.
- **Live check against the dev database** (real logs from Phases 1-5): each admin's feed and audit view showed no
  other tenant's users, no `650,000` and no "Salary Bands" title; in acme's audit view 184 of 201 rows withhold at
  least one chunk the admin may not read (every withheld id exists: these are ACL withholdings, not deleted chunks).
  An employee gets 403, no token 401.
- **A misleading number found and labelled:** only 235 of acme's 1,131 logged queries carry a shadow cost (none
  before Phase 4), so the modelled saving (USD 0.093, hits x mean answered-miss cost) exceeded the recorded shadow
  total (USD 0.037). The summary now returns `costed_queries`, and the page states how many queries carry a cost.

## Phase 6 fresh-clone check (2026-11-06)

**Gate item: fresh clone → `docker compose up` → seeded demo → working query, nothing manual beyond `.env`.**

**Rehearsal first** (a clone of the local repository into `~/gateway_fresh_rehearsal`, own compose project, ports and
volumes, so nothing of the dev stack was visible). It found what breaks between "works on my machine" and "works from
a clone"; each was fixed before the real check:
1. **The entrypoint was not executable.** The repository is on NTFS, where git records no file mode
   (`core.filemode=false`), so the clone checked the script out 644 and the container could not start it. The mode
   is now set in the Dockerfile (`COPY --chmod=0755`), independent of the checkout, and recorded in git.
2. **The README's own example query was always refused.** It asked about annual leave as `employee@acme.example`;
   the leave policy is HR-only. It had been written without running it as that user. The README now asks the same
   question as HR (answered) and as an employee (refused), which is the ACL in one example.
3. **`scripts/resolve_models.py` had been broken since Phase 4.** `with_retry` gained three required arguments and
   the script was never updated; the verification loop's mypy covered `gateway/` only. Fixed, and the loop now runs
   `mypy gateway/ scripts/ eval/` (it found three further type errors from reused variable names; none a runtime bug).
4. **A wrong model ID was found late:** a blank one after ~2 minutes of seeding, a mistyped one at the first query.
   The container now checks the configured ID against the provider's live roster before migrating or seeding, and
   stops with the valid IDs listed (tested with a mistyped ID: exits in seconds).
5. Also: `APP_HOST_PORT` documented in `.env.example`; a plain `docker compose up` now starts the app, so the
   development command is `docker compose up -d --wait postgres redis`.

**The real check**: cloned from GitHub on Windows to `D:\hamza\gateway_fresh` (HEAD `e727330`, clean tree, LF
endings kept), run from WSL2 with its own compose project and ports (`-p gwfresh`; 5433, 6381, 8001) so the dev
stack's volumes could not be reused. Only `.env` was written: 9 keys, of which 5 are required of a real user (two API
keys, two model IDs, `JWT_SECRET`); the others are the Postgres password and the three port moves this machine needed.

| Step | Result |
|---|---|
| Build, `docker compose build --no-cache --pull` | **222 s**, every build step executed; the two base images were already present, so their download is not included |
| First start, `docker compose up -d --wait` | **211 s** to healthy: roster check, 11 migrations, weights download into a new volume, 50 documents / 251 chunks seeded (seeding 119 s) |
| Restart (rehearsal) | 17 s; seeding skipped ("corpus already seeded") |
| Query, HR, annual leave | answered, "22 working days", cited Leave Policy and Employee Handbook |
| Same query, employee | refused |
| Dashboard | shell 200; the admin's summary counts the 2 queries |
| Graph | 0 entities, 0 relations, 0 extraction rows; the container reports `RETRIEVAL_MODE=hybrid`, routing off, cache on |
| README snippet | extracted from README.md and run verbatim (port substituted): both outcomes as stated |

**Nothing broke in the real check**, because the rehearsal had already found the breaks. The README's setup section
claims exactly this: four commands plus five `.env` values, with the measured times.

## Phase 6 scope added beyond the spec: `/chat` (fixed 2026-11-06, before any chat code)

**Reason (user):** the dashboard serves admins watching the system; there was no interface for the person asking
questions, which makes the product impossible to demo to a non-technical viewer. The spec's Phase 6 lists a
dashboard, packaging and a demo, not a query page; this is added scope, recorded as such.

**Design.** `GET /chat` is a static page (no data, no token needed to load it): the existing demo sign-in, a question
box, and each answer rendered with its citations as document title and heading path. It calls the existing
`POST /v1/query` with exactly `{"question": ...}`; no backend change beyond the route serving the page. `/v1/query`
returns JSON, so the page renders it with `textContent`, as the dashboard's tiles do (HTMX swaps server-rendered HTML,
and a server-rendered fragment would be a backend change). A refusal is shown exactly as the API returns it, in the
same element and style as an answer, with no wording of its own: P4 indistinguishability applies to the UI.

**Probes** (`eval/adversarial_chat.jsonl`, 11), each with a live control (invariant 18):
- **Role permits** (2): through the request the page sends, an employee and another tenant's HR user asking about
  the HR-only leave policy get none of its content; live: HR asking the same gets "22 working days".
- **Refusal indistinguishable** (1): the employee's refusal equals a genuinely unanswerable question's (answer,
  refused, citations); live: HR is answered.
- **No chunk text** (2): with a model that answers without quoting, the response carries no sentence of the cited
  chunk (live: the chunk holds it); the `Citation` model has no content field.
- **Text-only rendering** (2, structural): the page's script uses no `innerHTML`, `outerHTML`,
  `insertAdjacentHTML`, `document.write`, `eval` or `new Function`, and reads only `answer`, `refused`, `citations`,
  `document_title`, `heading_path`; live: each checker flags a mutated page.
- **No refusal wording** (1, structural): the page contains none of "permission", "not allowed", "access denied",
  "restricted", "forbidden", "don't have access"...; live: the checker flags a mutant.
- **Endpoints** (1, structural): the page fetches only `/v1/auth/token` and `/v1/query`; live: a mutant is flagged.
- **Shell holds no data** (1); **markup in a question** (1): the API answers it as JSON, never HTML.

**Correction before the first run (recorded 2026-11-06, no test had run):** c001 and c002 were written as
`expected: refuse`. Whether a model refuses is its choice (a real model refused in the fresh-clone check), and the
isolation suites run stubs, never a real model (`tests/test_acl_isolation.py`, module docstring). They now expect
`no_leak` and run under a stub that quotes every source it receives, the worst case: the employee's answer must
contain none of the HR-only content, while HR asking the same gets it. The refusal path is c003's: an ACL refusal
must equal a genuinely unanswerable question's, byte for byte.

**Not covered by the suite, stated in advance:** the page's JavaScript is not executed in tests (Node is not a
project dependency, and an isolation test may not skip). What the browser does with the response is guaranteed by
construction (text-only DOM writes, checked structurally) and by a browser check, not by an executed test.

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
