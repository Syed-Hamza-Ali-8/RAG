"""Document titles of chunks a caller may read (Phase 6 dashboard, audit view).

An audit row lists the chunk ids that reached the model for another user, who may hold roles the viewing
admin does not. Titles are returned only for chunks the viewer may read under the same ACL predicate as
retrieval; the rest are counted, never named (EVAL_RESULTS.md, Phase 6 dashboard design, decision 2).
"""

from uuid import UUID

import asyncpg

from gateway.security import acl


def _titles_sql() -> str:
    # $1 chunk ids; $2-$4 the viewer's ACL (tenant, roles, clearance). Constant text plus acl_predicate's
    # validated alias and positions; every value is a bound parameter.
    return (
        "SELECT DISTINCT d.title FROM chunks c JOIN documents d ON d.id = c.document_id "  # noqa: S608
        "WHERE c.id = ANY($1::uuid[]) AND " + acl.acl_predicate("c", 2) + " ORDER BY d.title"
    )


def _readable_count_sql() -> str:
    return "SELECT count(*) FROM chunks c WHERE c.id = ANY($1::uuid[]) AND " + acl.acl_predicate("c", 2)  # noqa: S608


async def readable_titles(
    conn: asyncpg.Connection, acl_filter: acl.AclFilter, chunk_ids: list[UUID]
) -> tuple[list[str], int]:
    """(titles of the readable chunks, number of readable chunks)."""
    if not chunk_ids:
        return [], 0
    titles = [r["title"] for r in await conn.fetch(_titles_sql(), chunk_ids, *acl_filter.params())]
    readable: int = await conn.fetchval(_readable_count_sql(), chunk_ids, *acl_filter.params())
    return titles, readable
