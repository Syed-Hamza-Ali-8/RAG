"""Writes query_log rows (migration 005). Cache, routing and cost columns stay NULL until Phase 4."""

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


async def write_query_log(conn: asyncpg.Connection, e: QueryLogEntry) -> None:
    await conn.execute(
        """
        INSERT INTO query_log (tenant_id, route_tier, model_used, prompt_tokens,
                               completion_tokens, retrieval_ms, llm_ms, total_ms, refused)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
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
    )
