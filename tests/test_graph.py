"""Graph retrieval path: the walk filters ACLs on every traversed relation (corrections L, M, T)."""

from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID

import asyncpg
import pytest

from gateway.retrieval import graph
from gateway.retrieval.graph import graph_search
from gateway.security import acl
from gateway.security.acl import AclFilter

VEC = [1.0] + [0.0] * 383


@pytest.fixture
async def g(pool: asyncpg.Pool) -> AsyncIterator[dict[str, Any]]:
    """Tenant graphco. Seed chunk S (public) relates A-Y. P_hr (HR-only, clearance 2) relates A-B;
    P_pub (public)
    relates B-C. The only route from the seeds to P_pub runs through the HR-only relation A-B."""
    async with pool.acquire() as conn:
        tid = await conn.fetchval(
            "INSERT INTO tenants (slug, name) VALUES ('graphco', 'GraphCo') "
            "ON CONFLICT (slug) DO UPDATE SET name = 'GraphCo' RETURNING id"
        )
        await conn.execute("DELETE FROM documents WHERE tenant_id = $1", tid)
        await conn.execute("DELETE FROM entities WHERE tenant_id = $1", tid)
        doc = await conn.fetchval(
            "INSERT INTO documents (tenant_id, slug, title) VALUES ($1, 'g', 'G') RETURNING id", tid
        )

        async def chunk(n: int, text: str, roles: list[str], clearance: int) -> UUID:
            cid: UUID = await conn.fetchval(
                "INSERT INTO chunks (tenant_id, document_id, ordinal, content, token_count, embedding, "
                "allowed_roles, min_clearance) VALUES ($1, $2, $3, $4, 1, $5, $6, $7) RETURNING id",
                tid,
                doc,
                n,
                text,
                VEC,
                roles,
                clearance,
            )
            return cid

        s = await chunk(0, "seed", [], 0)
        p_hr = await chunk(1, "restricted link", ["hr"], 2)
        p_pub = await chunk(2, "public but only reachable through the restricted link", [], 0)
        ent = {}
        for name in ("A", "Y", "B", "C"):
            ent[name] = await conn.fetchval(
                "INSERT INTO entities (tenant_id, name, norm, entity_type) "
                "VALUES ($1, $2, $3, 'ORG') RETURNING id",
                tid,
                name,
                name.lower(),
            )
        for src, tgt, cid in (("A", "Y", s), ("A", "B", p_hr), ("B", "C", p_pub)):
            await conn.execute(
                "INSERT INTO relations (tenant_id, source_id, target_id, relation, chunk_id) "
                "VALUES ($1, $2, $3, 'r', $4)",
                tid,
                ent[src],
                ent[tgt],
                cid,
            )
    yield {"tenant": tid, "s": s, "p_hr": p_hr, "p_pub": p_pub}
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM tenants WHERE id = $1", tid)


async def _walk(pool: asyncpg.Pool, g: dict[str, Any], roles: tuple[str, ...], clearance: int) -> set[UUID]:
    async with pool.acquire() as conn:
        hits = await graph_search(
            conn,
            acl_filter=AclFilter(g["tenant"], roles, clearance),
            seed_chunk_ids=[g["s"]],
            query_embedding=VEC,
            max_depth=2,
            top_k=20,
        )
    return {h.chunk_id for h in hits}


async def test_hr_walks_the_full_path(pool: asyncpg.Pool, g: dict[str, Any]) -> None:
    assert await _walk(pool, g, ("employee", "hr"), 2) == {g["s"], g["p_hr"], g["p_pub"]}


async def test_a_restricted_relation_is_never_traversed(pool: asyncpg.Pool, g: dict[str, Any]) -> None:
    # The employee may read P_pub, but the only route to it is the HR-only relation A-B: walking through it
    # would reveal that B (and C) exist. Correction T: neither the restricted chunk nor P_pub is returned.
    assert await _walk(pool, g, ("employee",), 0) == {g["s"]}


async def test_another_tenants_graph_is_invisible(pool: asyncpg.Pool, g: dict[str, Any]) -> None:
    other = await pool.fetchval(
        "INSERT INTO tenants (slug, name) VALUES ('graphco2', 'G2') "
        "ON CONFLICT (slug) DO UPDATE SET name = 'G2' RETURNING id"
    )
    async with pool.acquire() as conn:
        hits = await graph_search(
            conn,
            acl_filter=AclFilter(other, ("hr",), 3),
            seed_chunk_ids=[g["s"]],
            query_embedding=VEC,
            max_depth=2,
            top_k=20,
        )
    assert hits == []


def _filter_only_the_result(real: Callable[[str, int], str]) -> Callable[[str, int], str]:
    """Mutant: the first predicate composed (the recursive step) becomes TRUE; the second (the result)
    stays."""
    calls = {"n": 0}

    def fake(alias: str, first: int) -> str:
        calls["n"] += 1
        if calls["n"] % 2 == 1:
            return (
                f"(${first}::uuid IS NOT NULL AND ${first + 1}::text[] IS NOT NULL"
                f" AND ${first + 2}::int IS NOT NULL)"
            )
        return real(alias, first)

    return fake


async def test_filtering_only_the_result_would_leak_the_path(
    pool: asyncpg.Pool, g: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The spec's §4.3 query filters only the final chunks. With the walk's own filter removed, the employee
    # reaches P_pub through the restricted relation: the per-step filter is what stops it (the test has
    # teeth).
    monkeypatch.setattr(acl, "acl_predicate", _filter_only_the_result(acl.acl_predicate))
    assert g["p_pub"] in await _walk(pool, g, ("employee",), 0)


def test_graph_sql_filters_inside_the_walk_and_on_the_result() -> None:
    sql = graph._graph_sql()
    pred = acl.acl_predicate("c", 2)
    assert sql.count(pred) == 2
    assert sql.index(pred) < sql.index(") SELECT")  # the first one is inside the recursive CTE
