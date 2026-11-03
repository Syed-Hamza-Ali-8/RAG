"""Graph retrieval path: a depth-capped, bidirectional walk over relations, ACL-filtered at every step.

Corrections L, M and T: an entity is reachable only through a relation whose provenance chunk the caller may
read, and that holds for every relation the walk traverses, not only for the chunks returned at the end (the
spec's own §4.3 query filters only the end, which would reveal an entity's existence through a restricted
relation). The walk follows relations in both directions at each step, up to a fixed depth.

Seeds are the entities attached, through relations, to the chunks the other paths already ranked highest
(all of which the caller may read). Candidates are the provenance chunks reached, ordered by the depth at
which they were reached, then by how many reached relations support them (pre-registered), or by cosine
similarity to the question (M2 option A, EVAL_RESULTS.md).
"""

from typing import Literal
from uuid import UUID

import asyncpg

from gateway.retrieval.vector import RetrievedChunk
from gateway.security import acl


def _seeds_sql() -> str:
    # $1 seed chunk ids, $2 tenant. Reads relations only; the seed chunks were returned by ACL-filtered paths.
    return (
        "SELECT DISTINCT e FROM relations r, LATERAL unnest(ARRAY[r.source_id, r.target_id]) e "
        "WHERE r.tenant_id = $2 AND r.chunk_id = ANY($1::uuid[])"
    )


GraphOrder = Literal["depth_support", "cosine"]
# Constant ORDER BY clauses; the setting selects one, it is never interpolated from input.
_ORDER = {
    "depth_support": " ORDER BY min(w.depth), count(DISTINCT r.id) DESC, c.id LIMIT $6",
    "cosine": " ORDER BY 1 - (c.embedding <=> $7) DESC, c.id LIMIT $6",  # M2 option A
}


def _graph_sql(order: GraphOrder = "depth_support") -> str:
    # $1 seed entity ids, $2-$4 ACL (tenant, roles, clearance), $5 max depth, $6 limit, $7 query embedding.
    # The predicate appears twice: inside the recursive step (every traversed relation) and on the result.
    # Constant text plus acl_predicate's validated alias/positions; all values are bound parameters.
    return (
        "WITH RECURSIVE walk(entity_id, depth) AS ("  # noqa: S608
        " SELECT e, 0 FROM unnest($1::uuid[]) e"
        " UNION"
        " SELECT CASE WHEN r.source_id = w.entity_id THEN r.target_id ELSE r.source_id END, w.depth + 1"
        " FROM walk w"
        " JOIN relations r ON r.tenant_id = $2 AND (r.source_id = w.entity_id OR r.target_id = w.entity_id)"
        " JOIN chunks c ON c.id = r.chunk_id"
        " WHERE w.depth < $5 AND " + acl.acl_predicate("c", 2) + ")"
        " SELECT c.id, c.document_id, d.slug, d.title, c.ordinal, c.heading_path, c.content,"
        " 1 - (c.embedding <=> $7) AS score, min(w.depth) AS depth, count(DISTINCT r.id) AS support"
        " FROM walk w"
        " JOIN relations r ON r.tenant_id = $2 AND (r.source_id = w.entity_id OR r.target_id = w.entity_id)"
        " JOIN chunks c ON c.id = r.chunk_id"
        " JOIN documents d ON d.id = c.document_id AND d.tenant_id = c.tenant_id"
        " WHERE " + acl.acl_predicate("c", 2) + " GROUP BY c.id, d.slug, d.title" + _ORDER[order]
    )


async def graph_search(
    conn: asyncpg.Connection,
    *,
    acl_filter: acl.AclFilter,
    seed_chunk_ids: list[UUID],
    query_embedding: list[float],
    max_depth: int,
    top_k: int,
    order: GraphOrder = "depth_support",
) -> list[RetrievedChunk]:
    seeds = [r[0] for r in await conn.fetch(_seeds_sql(), seed_chunk_ids, acl_filter.tenant_id)]
    if not seeds:
        return []
    rows = await conn.fetch(_graph_sql(order), seeds, *acl_filter.params(), max_depth, top_k, query_embedding)
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
