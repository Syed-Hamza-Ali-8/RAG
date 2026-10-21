"""pgvector cosine search, scoped by tenant in SQL.

Phase 1 has no caller identity, so no role/clearance predicate yet; Phase 3 adds it here
via gateway/security/acl.py.
"""

from dataclasses import dataclass
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    document_slug: str
    document_title: str
    ordinal: int
    heading_path: str | None
    content: str
    score: float


async def vector_search(
    conn: asyncpg.Connection, *, tenant_id: UUID, query_embedding: list[float], top_k: int
) -> list[RetrievedChunk]:
    rows = await conn.fetch(
        """
        SELECT c.id, c.document_id, d.slug, d.title, c.ordinal, c.heading_path, c.content,
               1 - (c.embedding <=> $2) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id AND d.tenant_id = c.tenant_id
        WHERE c.tenant_id = $1
        ORDER BY c.embedding <=> $2
        LIMIT $3
        """,
        tenant_id,
        query_embedding,
        top_k,
    )
    return [
        RetrievedChunk(
            chunk_id=r["id"],
            document_id=r["document_id"],
            document_slug=r["slug"],
            document_title=r["title"],
            ordinal=r["ordinal"],
            heading_path=r["heading_path"],
            content=r["content"],
            score=float(r["score"]),
        )
        for r in rows
    ]
