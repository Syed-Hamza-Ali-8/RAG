"""Readable titles for the audit view: titles only for chunks the viewer may read."""

from uuid import UUID

import asyncpg

from gateway.retrieval import titles
from gateway.retrieval.titles import readable_titles
from gateway.security import acl
from gateway.security.acl import AclFilter

VEC = [1.0] + [0.0] * 383


async def _seed(pool: asyncpg.Pool) -> tuple[UUID, UUID, UUID]:
    async with pool.acquire() as conn:
        tid: UUID = await conn.fetchval(
            "INSERT INTO tenants (slug, name) VALUES ('titleco', 'T') "
            "ON CONFLICT (slug) DO UPDATE SET name = 'T' RETURNING id"
        )
        await conn.execute("DELETE FROM documents WHERE tenant_id = $1", tid)
        ids = []
        for slug, title, roles in (("pub", "Public Handbook", []), ("pay", "Salary Bands", ["hr"])):
            doc = await conn.fetchval(
                "INSERT INTO documents (tenant_id, slug, title) VALUES ($1, $2, $3) RETURNING id",
                tid,
                slug,
                title,
            )
            ids.append(
                await conn.fetchval(
                    "INSERT INTO chunks (tenant_id, document_id, ordinal, content, token_count, embedding, "
                    "allowed_roles) VALUES ($1, $2, 0, 'x', 1, $3, $4) RETURNING id",
                    tid,
                    doc,
                    VEC,
                    roles,
                )
            )
    return tid, ids[0], ids[1]


async def test_restricted_titles_are_withheld_and_counted(pool: asyncpg.Pool) -> None:
    tid, pub, pay = await _seed(pool)
    async with pool.acquire() as conn:
        admin = await readable_titles(conn, AclFilter(tid, ("employee", "admin"), 3), [pub, pay])
        hr = await readable_titles(conn, AclFilter(tid, ("employee", "hr"), 2), [pub, pay])
        other = await readable_titles(conn, AclFilter(UUID(int=0), ("hr",), 3), [pub, pay])
    assert admin == (["Public Handbook"], 1)
    assert hr == (["Public Handbook", "Salary Bands"], 2)
    assert other == ([], 0)


def test_both_title_queries_carry_the_acl_predicate() -> None:
    pred = acl.acl_predicate("c", 2)
    assert pred in titles._titles_sql() and pred in titles._readable_count_sql()
