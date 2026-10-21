"""Writes query_log rows (migrations 005-007). Cache, routing and cost columns stay NULL until Phase 4.

answer_raw holds LLM output, which may quote document content: it lives in the database
only and is never written to application logs."""

from dataclasses import dataclass
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class QueryLogEntry:
    tenant_id: UUID
    route_tier: str
    model_used: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    retrieval_ms: int
    llm_ms: int | None
    total_ms: int
    refused: bool
    answer_raw: str | None
    citations_valid: int | None
    citations_rejected: int | None
    prompt_version: str | None


async def write_query_log(conn: asyncpg.Connection, e: QueryLogEntry) -> None:
    await conn.execute(
        """
        INSERT INTO query_log (tenant_id, route_tier, model_used, prompt_tokens,
                               completion_tokens, retrieval_ms, llm_ms, total_ms, refused,
                               answer_raw, citations_valid, citations_rejected, prompt_version)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """,
        e.tenant_id,
        e.route_tier,
        e.model_used,
        e.prompt_tokens,
        e.completion_tokens,
        e.retrieval_ms,
        e.llm_ms,
        e.total_ms,
        e.refused,
        e.answer_raw,
        e.citations_valid,
        e.citations_rejected,
        e.prompt_version,
    )
