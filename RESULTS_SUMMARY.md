# Gateway: results summary (Phases 1-4)

Every number here is taken from `EVAL_RESULTS.md`, whose section for each is named in brackets. Corpus: 50 synthetic
documents, two tenants, 251 chunks; golden set: 100 questions (85 answerable, 15 unanswerable), each asked as a real
seeded user. Generator `openai/gpt-oss-20b`; judge `openai/gpt-oss-120b`. Negative results are listed with the same
weight as positive ones.

## Phase 1: baseline RAG
Vector retrieval, cited answers, refusal when no valid citation exists. End-to-end latency p50 1,094 ms, p95 2,275 ms
over 20 queries [Phase 1 — Baseline latency].

## Phase 2: evaluation harness
- Recall@6 77.1%; multi-hop all-hops@10 44%; buried-fact recall@6 85% (17/20). Unanswerable questions refused 15/15,
  no hallucination [Golden set baseline — Phase 2].
- Correct 85.9% (73/85, judge-v1). 10 answerable questions refused: 9 genuine retrieval misses and 1 generation
  truncated at the token limit, recorded at the time as a refusal and corrected later [Corrected refusal counts].
- **The judge had a blind spot.** judge-v1 caught 5/5 fabrications and 5/5 wrong-question answers but **0/5 bad
  citations**: it never checked that a cited chunk supports its sentence. judge-v2 closed it (10/10 in calibration)
  [Judge calibration — judge-v1; judge-v2]. In the field the judge has contradicted itself twice on identical content
  (q054, q005) [judge-v2, field data points].

## Phase 3: permission-aware retrieval
- **Isolation:** 43 retrieval probes and 19 admin probes; with the ACL predicate removed every leak probe fails
  (39/39); with it in, all pass. 132 cross-tenant queries over 11 shared document titles returned 0 chunks from the
  other tenant. 101/101 queries audited [Phase 3 gate: evidence].
- **Phase 2 was leaking without anyone noticing:** 11 of its answers cited a chunk the asking user may not read, and
  187 restricted chunks reached the model. In Phase 3, 0 and 0. One question (q052) was answered correctly in Phase 2
  only through the leak; closing it cost that answer [A correct answer that should never have been possible].
- Recall@6 rose to 86.5%. **This is not a retrieval improvement:** each user now competes against fewer chunks. It
  was predicted before the run and is not claimed as a gain [Phase 3 vs Phase 2].
- Citations supported in 74 of 79 answers; the 5 misattributed ones are all stacked double citations
  [Golden set baseline — Phase 3; Citation misattribution].

## Phase 4: semantic cache and cost-aware routing
- **Similarity alone cannot gate a cache on this corpus.** A near-miss pair sits at cosine 0.9948; the only real
  paraphrase at 0.819. The cache therefore also requires the same content words [Phase 4 semantic cache finding].
- **Paraphrases never hit: 0/25 at every threshold.** That is the price of the word check. The threshold (0.95) is the
  midpoint of a flat region, not a tuned optimum [Phase 4 cache threshold sweep: results].
- **On repeated traffic shaped like real use, 143/250 requests (57.2%) hit, and shadow cost fell 54.9%, both exactly
  as predicted before running.** Hits return in ~19 ms against ~0.8 s for a model call [Phase 4 gate: results].
- On a single pass of unique questions the cache hit nothing, changed no answer and left retrieval identical; it adds
  ~2 ms to every miss [Phase 4 Run A against its pre-registration].
- **Routing ships off.** No question needed the larger model; it was worse (22/25 correct against 24/25) at 1.94×
  the cost. On the hardest failure (q051) the small model returned nothing and the large one a confident, cited, wrong
  date. **In a system sold on trustworthy citations, a wrong answer is worse than no answer.** Answer quality here is
  bounded by retrieval, not by the generator [Phase 4 routing: results].
- **The latency drop was not ours:** p95 fell 1,013 ms against Phase 2 with zero cache hits; it is the model provider's
  variance, not a Phase 4 effect. Cost per query moved −5.1% [Phase 4 gate: results].
- Correct 75/85 against Phase 3's 77/85, within the noise band set in advance; faithful 79/80 [Phase 4 Run A].

## How these numbers were produced
Every expectation, threshold and pass criterion was written down and committed before the run that tested it,
misses included (for example: the large model was predicted to use more tokens and used fewer). Free-tier budgets
split full runs across days; nothing was forced past a budget or safety check. Each phase is compared only with the
one before it.
