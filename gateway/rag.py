"""Request path: embed → semantic cache (tenant + role signature + content words) → ACL-filtered vector
search → prompt → LLM → citation check → cache store (answers only) → query_log + audit_log.
Permissions come from the AuthContext, resolved from the database per request."""

import logging
import time
from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

import asyncpg

from gateway.cache import semantic
from gateway.cache.semantic import CacheConfig, CachedAnswer
from gateway.deps import AuthContext
from gateway.errors import TenantNotFound, TruncatedCompletion
from gateway.ingest.embedder import Embedder
from gateway.llm.prompts import PROMPT_VERSION, REFUSAL_MESSAGE, build_messages, source_label
from gateway.llm.provider import LLM
from gateway.models.query import Citation, QueryResponse, Timings
from gateway.query_log import QueryLogEntry, write_query_log
from gateway.retrieval.vector import denied_count, readable_count, vector_search
from gateway.routing.classifier import complexity
from gateway.routing.policy import Price, Router, shadow_cost
from gateway.security.audit import AuditEntry, write_audit
from gateway.security.guardrails import check_citations

log = logging.getLogger(__name__)


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


async def resolve_tenant(conn: asyncpg.Connection, slug: str) -> UUID:
    tenant_id: UUID | None = await conn.fetchval("SELECT id FROM tenants WHERE slug = $1", slug)
    if tenant_id is None:
        raise TenantNotFound(slug)
    return tenant_id


async def _cache_hit(
    conn: asyncpg.Connection,
    cache: CacheConfig,
    auth: AuthContext,
    question: str,
    query_vec: list[float],
) -> CachedAnswer | None:
    hit = await semantic.lookup(
        conn,
        tenant_id=auth.tenant_id,
        signature=semantic.role_signature(auth.roles, auth.clearance),
        key=semantic.content_key(question),
        embedding=query_vec,
        threshold=cache.threshold,
    )
    if hit is None:
        return None
    # Defence in depth: the key already scopes the entry to this permission set, and ACL changes wipe the
    # tenant's cache (migration 003). Still, never serve a citation the caller cannot read right now.
    cited = list({c.chunk_id for c in hit.citations})
    if await readable_count(conn, acl_filter=auth.acl(), chunk_ids=cited) != len(cited):
        log.warning("cache entry %s cites chunks the caller cannot read; discarded", hit.entry_id)
        await semantic.discard(conn, hit.entry_id)
        return None
    return hit


async def _serve_cached(
    pool: asyncpg.Pool,
    llm: LLM,
    auth: AuthContext,
    question: str,
    hit: CachedAnswer,
    started: float,
    lookup_ms: int,
) -> QueryResponse:
    total_ms = _ms(started)
    async with pool.acquire() as conn:
        query_log_id = await write_query_log(
            conn,
            QueryLogEntry(
                tenant_id=auth.tenant_id,
                route_tier="cached",
                model_used=hit.model_used,
                prompt_tokens=None,
                completion_tokens=None,
                retrieval_ms=total_ms,
                llm_ms=None,
                total_ms=total_ms,
                refused=False,
                answer_raw=None,
                citations_valid=None,
                citations_rejected=None,
                prompt_version=None,
                outcome="answered",
                cache_hit=True,
                est_cost_usd=Decimal(0),
                cache_lookup_ms=lookup_ms,
            ),
        )
        # Correction O: a hit copies retrieved_ids from the cached citations and sets the flag.
        await write_audit(
            conn,
            AuditEntry(
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                user_roles=auth.roles,
                user_clearance=auth.clearance,
                query_text=question,
                retrieved_ids=list(dict.fromkeys(c.chunk_id for c in hit.citations)),
                denied_count=0,
                refused=False,
                answer=hit.answer,
                served_from_cache=True,
                query_log_id=query_log_id,
            ),
        )
    return QueryResponse(
        answer=hit.answer,
        refused=False,
        citations=hit.citations,
        model=hit.model_used,
        tier=llm.tier,
        prompt_version=PROMPT_VERSION,
        timings=Timings(retrieval_ms=total_ms, llm_ms=None, total_ms=total_ms),
    )


async def answer_query(
    pool: asyncpg.Pool,
    embedder: Embedder,
    llm: LLM,
    *,
    auth: AuthContext,
    question: str,
    top_k: int,
    cache: CacheConfig | None = None,
    router: Router | None = None,
    llms: Mapping[str, LLM] | None = None,
    prices: Mapping[str, Price | None] | None = None,
) -> QueryResponse:
    """`llm` answers every query unless `router` is set; then each query goes to `llms[tier]` for the tier
    its complexity score selects. `prices` (per tier) give the shadow cost; a missing price → unknown."""
    started = time.perf_counter()
    acl_filter = auth.acl()
    use_cache = cache is not None and not cache.bypassed(question)
    lookup_ms: int | None = None
    async with pool.acquire() as conn:
        query_vec = await embedder.embed_query(question)
        if use_cache:
            assert cache is not None
            lookup_started = time.perf_counter()
            hit = await _cache_hit(conn, cache, auth, question, query_vec)
            lookup_ms = _ms(lookup_started)
            if hit is not None:
                return await _serve_cached(pool, llm, auth, question, hit, started, lookup_ms)
        chunks = await vector_search(conn, acl_filter=acl_filter, query_embedding=query_vec, top_k=top_k)
        denied = await denied_count(conn, acl_filter=acl_filter, query_embedding=query_vec, top_k=top_k)
    retrieval_ms = _ms(started)

    model: str | None = None
    llm_ms: int | None = None
    prompt_tokens = completion_tokens = None
    answer_raw: str | None = None
    citations_valid: int | None = None
    citations_rejected: int | None = None
    answer = REFUSAL_MESSAGE
    citations: list[Citation] = []
    truncated: TruncatedCompletion | None = None
    score: float | None = None
    generator = llm
    if router is not None and chunks:
        assert llms is not None
        score = complexity(question, [c.score for c in chunks]).score
        generator = llms[router.route(score)]

    # Nothing permitted retrieved → refuse without an LLM call. This branch depends only on what the
    # caller may read, never on what was denied, so it reveals nothing about restricted documents.
    if chunks:
        llm_started = time.perf_counter()
        try:
            completion = await generator.complete(build_messages(question, chunks))
        except TruncatedCompletion as exc:
            truncated = exc
        llm_ms = _ms(llm_started)
    if truncated is not None:
        # Logged and audited like any query that reached the LLM, then raised: never a refusal.
        model, answer_raw = truncated.model, truncated.text
        prompt_tokens, completion_tokens = truncated.prompt_tokens, truncated.completion_tokens
    elif chunks:
        model = completion.model
        prompt_tokens, completion_tokens = completion.prompt_tokens, completion.completion_tokens
        answer_raw = completion.text
        check = check_citations(completion.text, len(chunks))
        citations_valid, citations_rejected = len(check.valid_indices), check.rejected_count
        if check.invalid_labels:
            log.warning("answer cited non-existent sources: %s", check.invalid_labels)
        if check.grounded:
            answer = check.normalized_text.strip()
            citations = [
                Citation(
                    label=source_label(i),
                    chunk_id=chunks[i].chunk_id,
                    document_id=chunks[i].document_id,
                    document_slug=chunks[i].document_slug,
                    document_title=chunks[i].document_title,
                    chunk_ordinal=chunks[i].ordinal,
                    heading_path=chunks[i].heading_path,
                )
                for i in check.valid_indices
            ]

    refused = truncated is None and not citations
    # No chunks means no LLM call: the cost is zero, not unknown.
    cost = (
        shadow_cost((prices or {}).get(generator.tier), prompt_tokens, completion_tokens)
        if chunks
        else Decimal(0)
    )
    outcome = "truncated" if truncated is not None else ("refused" if refused else "answered")
    total_ms = _ms(started)
    async with pool.acquire() as conn:
        query_log_id = await write_query_log(
            conn,
            QueryLogEntry(
                tenant_id=auth.tenant_id,
                route_tier=generator.tier,
                model_used=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                retrieval_ms=retrieval_ms,
                llm_ms=llm_ms,
                total_ms=total_ms,
                refused=refused,
                answer_raw=answer_raw,
                citations_valid=citations_valid,
                citations_rejected=citations_rejected,
                prompt_version=PROMPT_VERSION if answer_raw is not None else None,
                outcome=outcome,
                cache_hit=False if use_cache else None,
                cache_lookup_ms=lookup_ms,
                complexity_score=score,
                est_cost_usd=cost,
            ),
        )
        if use_cache and outcome == "answered" and model is not None:
            # C8: only answered outcomes are stored; refusals and truncations never are.
            assert cache is not None
            await semantic.store(
                conn,
                tenant_id=auth.tenant_id,
                signature=semantic.role_signature(auth.roles, auth.clearance),
                key=semantic.content_key(question),
                question=question,
                embedding=query_vec,
                answer=answer,
                citations=citations,
                model_used=model,
                ttl_hours=cache.ttl_hours,
            )
        await write_audit(
            conn,
            AuditEntry(
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                user_roles=auth.roles,
                user_clearance=auth.clearance,
                query_text=question,
                retrieved_ids=[c.chunk_id for c in chunks],
                denied_count=denied,
                refused=refused,
                answer="" if truncated is not None else answer,
                query_log_id=query_log_id,
            ),
        )
    if truncated is not None:
        raise truncated
    return QueryResponse(
        answer=answer,
        refused=refused,
        citations=citations,
        model=model,
        tier=generator.tier,
        prompt_version=PROMPT_VERSION,
        timings=Timings(retrieval_ms=retrieval_ms, llm_ms=llm_ms, total_ms=total_ms),
    )
