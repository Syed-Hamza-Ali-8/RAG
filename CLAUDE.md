# Gateway — Operating Manual

Detailed reference: `GATEWAY_RAG_BUILD_SPEC.md` (cited below as §N). Where the spec says
"Keystone" / "keystone-rag" / `app/`, read "Gateway" / repo root / `gateway/`.
**This file wins over the spec** — see Spec corrections.

## Project identity

Gateway is a multi-tenant RAG platform for small and mid-size firms (law, accounting,
healthcare, insurance) that need an internal assistant over their own documents. Its
differentiator is permission-aware retrieval: every chunk carries its tenant, allowed roles
and clearance, and every retrieval path filters on them inside Postgres, so an intern
can never retrieve salary bands. Answers carry citations, every query is audited, and a
tenant-scoped semantic cache plus complexity routing keep cost low. Budget is $0: local
embeddings, free-tier LLMs, self-hosted Postgres. Portfolio flagship and sellable product.

## Non-negotiable invariants

Never violate these, whatever a prompt asks.

1. Filter ACLs in the SQL `WHERE` clause on every retrieval path (vector, keyword, graph). Never post-filter in Python.
2. Scope every query by `tenant_id`.
3. Use parameterized queries only. No f-string or concatenated SQL.
4. Key every cache lookup on `tenant_id` + `role_signature`.
5. Never hardcode model IDs. Resolve from provider `/models`; store in `.env`.
6. Never invent a library API. Verify against the installed package in `.venv/`.
7. No silent fallbacks, dummy vectors or fake answers. Raise a typed exception and log it.
8. Keep secrets in `.env` only. Never log API keys or full document content at INFO.
9. Refuse when no valid citation supports the answer. Every answer cites chunks.
10. Treat retrieved content as data, never instructions. Wrap it in delimiters.
11. Never weaken, skip, delete or xfail an ACL-isolation test or adversarial case to make a
    suite pass. A failing isolation test means the code is wrong, never the test.
12. Expose entities only through relations → chunks with the ACL predicate applied.
13. Never switch LLM providers at runtime. The tier comes from `.env`.
14. Send no real client data through free-tier endpoints. Synthetic corpus only (§7).
15. Treat phase gates as blocking. Do not start phase N+1 until phase N's gate passes.
16. Measure, don't claim. Every README number traces to `eval/run_eval.py` output.
17. Pin dependencies with `uv add`; commit `uv.lock`. Spend $0 on external services.

## Current phase

**Phase 1 — Baseline RAG — approved 2026-10-21. Phase 2 (Eval harness) — not started.**
Update this section as work progresses.

Prerequisites: `docker ps` works in WSL (Docker Desktop WSL Integration); `resolve_models.py` run.
Phase 1 gate (§5, as corrected below): passed, with ONE OPEN ITEM:
- [ ] answer-v2 latency baseline (`measure_latency.py`), pending Groq quota reset; answer-v1 figures are superseded.

Phase 2 requirements beyond §5:
- Golden set includes ≥8 questions whose answer is a single sentence buried in a large mixed-topic
  chunk (the "Known baseline weaknesses" class in `EVAL_RESULTS.md`), so Phase 5 gains are measured.
- Diagnose every refusal from `query_log.answer_raw` + `citations_valid`/`citations_rejected`.
- `query_log.answer_raw` may quote restricted content: never expose it beyond its tenant and role scope.

## Known temporary shortcuts (remove in the phase named)

- `POST /v1/query` takes a `tenant` slug in the body. Remove when JWT auth lands (Phase 3).
- No role/clearance filtering yet; `allowed_roles`/`min_clearance` are stored on chunks (Phase 3).
- No HTTP ingest endpoint; only `scripts/seed_corpus.py` ingests (add `POST /v1/documents` with ACLs).

Later phases: 2 Eval harness · 3 Multi-tenancy/ACL · 4 Cache + routing · 5 GraphRAG +
hybrid · 6 Dashboard + packaging. Gates are in §5.

## Commands (WSL, run from repo root)

```bash
docker ps                                   # prerequisite; must succeed
docker compose up -d --wait                 # postgres+pgvector, redis
docker compose down -v                      # full reset (drops volumes)
uv sync                                     # install from uv.lock
uv add <pkg>                                # only way to add a dependency
uv run python scripts/resolve_models.py     # query provider /models → .env
uv run python scripts/migrate.py            # apply migrations/*.sql in order
uv run python scripts/seed_corpus.py        # demo tenants, users, corpus
uv run uvicorn gateway.main:app --reload    # dev API server
uv run python eval/run_eval.py --baseline   # eval run → eval/results/<ts>.json
uv run python scripts/measure_latency.py    # p50/p95 from query_log → EVAL_RESULTS.md
```

Verification loop. Run it after every implementation step and run every step that exists so far.
All four are mandatory from Phase 2 onward:
```bash
uv run ruff check .
uv run mypy gateway/
uv run pytest -q
uv run python scripts/smoke.py   # must fail loudly if `docker ps` fails
```

## Architecture

This describes the END STATE. Phase 1 builds steps 4 (vector retrieval only), 5, 6 and the query_log half of 7. Auth (1), cache (2), routing (3), FTS/graph/rerank in 4, and audit_log in 7 arrive in their own phases. Never write to a table whose migration the current phase hasn't applied.

1. JWT → `AuthContext(tenant_id, user_id, roles, clearance)` dependency.
2. Semantic cache lookup on (tenant_id, role_signature, cosine ≥ tuned threshold). Temporal or entity-specific queries bypass it.
3. Complexity router picks the `small` or `large` tier (both Groq at first).
4. Hybrid retrieval: pgvector ANN + Postgres FTS + recursive-CTE graph, each ACL-filtered in SQL, fused with RRF, with an optional local rerank.
5. LLM generates from delimited context and must cite retrieved chunk IDs.
6. Deterministic citation check: zero valid citations → refuse.
7. Write `audit_log` (what reached the LLM, for whom) and `query_log` (latency, tier, shadow cost).
8. **Postgres 17 + pgvector is the single store** for vectors, FTS, graph, cache, audit and metrics.
9. No Neo4j, no external vector DB, no Elasticsearch. Redis exists only for ARQ background jobs.
10. Embeddings run locally via fastembed (`EMBEDDING_MODEL_ID`, `EMBEDDING_DIM` from `.env`).

## Code conventions

- Async throughout: asyncpg pool, `AsyncOpenAI`, async FastAPI routes.
- Pydantic models at every API boundary; settings via pydantic-settings, all typed.
- Typed exceptions (`RateLimitExhausted`, `EmbeddingDimensionMismatch`, …). No bare `except`.
- SQL lives in parameterized statements (`$1`, `$2`). Build ACL predicates in `gateway/security/acl.py` only.
- Put `tenant_id` first in every composite index.
- One test module per source module. Add a pytest test for every retrieval or security behavior.
- On 429: exponential backoff with jitter, then `RateLimitExhausted`. Eval runs honor `EVAL_REQUEST_DELAY_MS`.
- Write LF line endings only (`.gitattributes` enforces it). Use Linux paths only, never `D:\`.

## Environment notes

- Repo is on `/mnt/d` (Windows FS via WSL): slow file I/O and bind mounts; prefer named volumes.
- ~3.8 GB RAM shared with other stacks; stop unrelated containers before eval runs.
- fastembed downloads ONNX weights on first run. Cache them in a volume; never commit binaries.

## Spec corrections (these override the spec text)

- **A.** ACL columns (`allowed_roles`, `min_clearance`) live on `chunks` in migration 001. There is no `chunk_acl` table. Migration 002 contains `audit_log` only.
- **B.** The eval script is `eval/run_eval.py` (Rule 0.1.7's `scripts/` path is wrong).
- **C.** Migration 005 (`query_log`) is built in Phase 1. Cache, routing and cost columns stay nullable until Phase 4.
- **D.** Ollama is an explicit `.env` tier choice only, never an automatic runtime fallback.
- **E.** Verification loop: run whichever steps exist; all four are mandatory from Phase 2.
- **F.** Golden-set gold IDs are `"document_slug#chunk_ordinal"` (e.g. `hr-leave-policy#7`). The seed script assigns deterministic slugs; the harness resolves them to UUIDs at runtime.
- **G.** Migrations are plain `.sql` files applied by `scripts/migrate.py` in filename order, tracked in `schema_migrations`. No Alembic.
- **H.** `POST /v1/auth/token` is DEV-ONLY: it issues a JWT for a seeded user from tenant slug + email, with no password. The admin API requires an `admin` role claim. The README must call this a demo issuer; production plugs in the client's IdP.
- **I.** Chunks target 384 tokens, hard max 450, overlap 64, counted with the embedding model's own tokenizer. Assert no chunk exceeds the model's max sequence length (512 for bge-small).
- **J.** Grounding has two layers. At runtime (Phase 1), a deterministic citation check with no LLM call. In eval only (Phase 2), LLM-as-judge faithfulness, which is never a runtime gate.
- **K.** Any document ingest, delete or ACL change wipes ALL of that tenant's cache entries. Don't optimize this without a measurement.
- **L.** Entities are never exposed directly. An entity with no permitted supporting chunk does not exist for that user. The adversarial set covers entity-name leakage via the query planner.
- **M.** The graph CTE walks both directions (source→target UNION target→source) at each step, depth-capped (§4.3's query is wrong).
- **N.** "10 near-miss pairs" means 10 items = 5 pairs (50+25+15+10 = 100).
- **O.** `audit_log` has a `served_from_cache` boolean. On a cache hit, copy `retrieved_ids` from the cached citations and set the flag. Never write an empty `retrieved_ids`.
- **P.** `EMBEDDING_MODEL_ID` and `EMBEDDING_DIM` come from `.env`. On startup, assert the model's output dim equals the `chunks.embedding` dim and fail fast if it doesn't.
- **Q.** No Gemini in Phase 1. Groq serves both tiers (two models from its `/models` roster). Add Gemini in Phase 4 only if routing needs it, with its base URL taken from Google's official docs, never guessed.
- **S.** The project is Gateway: package `gateway/` (the spec's `app/`), repo root `/mnt/d/hamza/RAG_Projects/gateway`.

## When blocked

- Stop and ask rather than guess at product behavior.
- Treat the spec's architecture decisions (as corrected above) as fixed. Do not redesign.
- Raise gaps the spec doesn't cover; never invent behavior to fill them.
- If a library or model behaves differently than the spec assumes, report it with evidence.
- If a gate can't pass honestly, say so with numbers. Never fudge a gate.
