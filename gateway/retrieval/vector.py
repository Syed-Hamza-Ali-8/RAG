"""pgvector cosine search with the ACL predicate in the SQL WHERE clause (invariant 1).

There is no unfiltered search function: every caller must pass an AclFilter.
"""

from dataclasses import dataclass
from uuid import UUID

import asyncpg

from gateway.security import acl


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


def _search_sql() -> str:
    # Composed per call from constants (see gateway.security.acl); $1 query vector, $2 limit, $3-$5 ACL.
    return (
        "SELECT c.id, c.document_id, d.slug, d.title, c.ordinal, c.heading_path, c.content, "
        "1 - (c.embedding <=> $1) AS score "
        "FROM chunks c JOIN documents d ON d.id = c.document_id AND d.tenant_id = c.tenant_id "
        "WHERE " + acl.acl_predicate("c", 3) + " "
        "ORDER BY c.embedding <=> $1 LIMIT $2"
    )


def _denied_sql() -> str:
    # Among the tenant's top-k candidates WITHOUT the role/clearance filter, how many the ACL removes.
    # Returns only a count to the audit log; no denied row's content ever leaves the database.
    return (
        # Constants plus acl_predicate's validated alias/positions; all values are bound parameters.
        "SELECT count(*) FILTER (WHERE NOT " + acl.acl_predicate("c", 3) + ") "  # noqa: S608
        "FROM (SELECT tenant_id, allowed_roles, min_clearance FROM chunks "
        "WHERE tenant_id = $3 ORDER BY embedding <=> $1 LIMIT $2) c"
    )


async def vector_search(
    conn: asyncpg.Connection, *, acl_filter: acl.AclFilter, query_embedding: list[float], top_k: int
) -> list[RetrievedChunk]:
    rows = await conn.fetch(_search_sql(), query_embedding, top_k, *acl_filter.params())
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


async def denied_count(
    conn: asyncpg.Connection, *, acl_filter: acl.AclFilter, query_embedding: list[float], top_k: int
) -> int:
    count: int = await conn.fetchval(_denied_sql(), query_embedding, top_k, *acl_filter.params())
    return count


def _permitted_sql() -> str:
    # How many of the given chunk ids the caller may read. $1 chunk ids, $2-$4 ACL. Used to re-check a
    # cache hit's citations before serving it (defence in depth on top of the role-signature key).
    # Constant text plus acl_predicate's validated alias/positions; all values are bound parameters.
    return "SELECT count(*) FROM chunks c WHERE c.id = ANY($1::uuid[]) AND " + acl.acl_predicate("c", 2)  # noqa: S608


async def readable_count(
    conn: asyncpg.Connection, *, acl_filter: acl.AclFilter, chunk_ids: list[UUID]
) -> int:
    count: int = await conn.fetchval(_permitted_sql(), chunk_ids, *acl_filter.params())
    return count
