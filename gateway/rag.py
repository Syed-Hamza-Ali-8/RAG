"""Phase 1 request path: embed → vector search → prompt → LLM → citation check → query_log."""

import logging
import time
from uuid import UUID

import asyncpg

from gateway.errors import TenantNotFound
from gateway.ingest.embedder import Embedder
from gateway.llm.prompts import PROMPT_VERSION, REFUSAL_MESSAGE, build_messages, source_label
from gateway.llm.provider import LLM
from gateway.models.query import Citation, QueryResponse, Timings
from gateway.query_log import QueryLogEntry, write_query_log
from gateway.retrieval.vector import vector_search
from gateway.security.guardrails import check_citations

log = logging.getLogger(__name__)


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


async def resolve_tenant(conn: asyncpg.Connection, slug: str) -> UUID:
    tenant_id: UUID | None = await conn.fetchval("SELECT id FROM tenants WHERE slug = $1", slug)
    if tenant_id is None:
        raise TenantNotFound(slug)
    return tenant_id


async def answer_query(
    pool: asyncpg.Pool,
    embedder: Embedder,
    llm: LLM,
    *,
    tenant_slug: str,
    question: str,
    top_k: int,
) -> QueryResponse:
    started = time.perf_counter()
    async with pool.acquire() as conn:
        tenant_id = await resolve_tenant(conn, tenant_slug)
        query_vec = await embedder.embed_query(question)
        chunks = await vector_search(conn, tenant_id=tenant_id, query_embedding=query_vec, top_k=top_k)
    retrieval_ms = _ms(started)

    model: str | None = None
    llm_ms: int | None = None
    prompt_tokens = completion_tokens = None
    answer_raw: str | None = None
    citations_valid: int | None = None
    citations_rejected: int | None = None
    answer = REFUSAL_MESSAGE
    citations: list[Citation] = []

    if chunks:  # nothing retrieved → refuse without an LLM call
        llm_started = time.perf_counter()
        completion = await llm.complete(build_messages(question, chunks))
        llm_ms = _ms(llm_started)
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

    refused = not citations
    total_ms = _ms(started)
    async with pool.acquire() as conn:
        await write_query_log(
            conn,
            QueryLogEntry(
                tenant_id=tenant_id,
                route_tier=llm.tier,
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
            ),
        )
    return QueryResponse(
        answer=answer,
        refused=refused,
        citations=citations,
        model=model,
        tier=llm.tier,
        prompt_version=PROMPT_VERSION,
        timings=Timings(retrieval_ms=retrieval_ms, llm_ms=llm_ms, total_ms=total_ms),
    )
