"""audit_log writes (migration 002): one row per query."""

import hashlib
from dataclasses import dataclass
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class AuditEntry:
    tenant_id: UUID
    user_id: UUID
    user_roles: tuple[str, ...]
    user_clearance: int
    query_text: str
    retrieved_ids: list[UUID]
    denied_count: int
    refused: bool
    answer: str
    served_from_cache: bool = False
    query_log_id: int | None = None


def answer_hash(answer: str) -> str:
    return hashlib.sha256(answer.encode("utf-8")).hexdigest()


async def write_audit(conn: asyncpg.Connection, e: AuditEntry) -> int:
    audit_id: int = await conn.fetchval(
        """
        INSERT INTO audit_log (tenant_id, user_id, user_roles, user_clearance, query_text, retrieved_ids,
                               denied_count, refused, answer_hash, served_from_cache, query_log_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        RETURNING id
        """,
        e.tenant_id,
        e.user_id,
        list(e.user_roles),
        e.user_clearance,
        e.query_text,
        e.retrieved_ids,
        e.denied_count,
        e.refused,
        answer_hash(e.answer),
        e.served_from_cache,
        e.query_log_id,
    )
    return audit_id
