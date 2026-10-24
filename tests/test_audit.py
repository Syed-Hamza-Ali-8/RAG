from uuid import UUID, uuid4

import asyncpg
import pytest

from gateway.security.audit import AuditEntry, answer_hash, write_audit


@pytest.fixture
async def tenant_id(pool: asyncpg.Pool) -> UUID:
    async with pool.acquire() as conn:
        tid: UUID = await conn.fetchval(
            "INSERT INTO tenants (slug, name) VALUES ('auditco', 'AuditCo') "
            "ON CONFLICT (slug) DO UPDATE SET name = 'AuditCo' RETURNING id"
        )
    return tid


def entry(tenant_id: UUID, **over: object) -> AuditEntry:
    fields: dict[str, object] = {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
        "user_roles": ("employee", "hr"),
        "user_clearance": 2,
        "query_text": "How much leave?",
        "retrieved_ids": [uuid4(), uuid4()],
        "denied_count": 3,
        "refused": False,
        "answer": "21 days [S1].",
    }
    fields.update(over)
    return AuditEntry(**fields)  # type: ignore[arg-type]


async def test_write_audit_stores_the_answer_hash_not_the_answer(pool: asyncpg.Pool, tenant_id: UUID) -> None:
    e = entry(tenant_id)
    async with pool.acquire() as conn:
        audit_id = await write_audit(conn, e)
        row = await conn.fetchrow("SELECT * FROM audit_log WHERE id = $1", audit_id)
    assert row["answer_hash"] == answer_hash("21 days [S1].") and len(row["answer_hash"]) == 64
    assert "21 days" not in str(dict(row).values())
    assert list(row["retrieved_ids"]) == e.retrieved_ids
    assert (list(row["user_roles"]), row["user_clearance"], row["denied_count"]) == (["employee", "hr"], 2, 3)
    assert row["served_from_cache"] is False


async def test_cache_hit_with_empty_retrieved_ids_is_refused_by_the_schema(
    pool: asyncpg.Pool, tenant_id: UUID
) -> None:
    # CLAUDE.md correction O: never an empty retrieved_ids on a cache hit.
    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await write_audit(conn, entry(tenant_id, served_from_cache=True, retrieved_ids=[]))
        await write_audit(conn, entry(tenant_id, served_from_cache=True))


async def test_audit_rows_go_with_their_tenant(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        tid: UUID = await conn.fetchval(
            "INSERT INTO tenants (slug, name) VALUES ('goneco', 'GoneCo') RETURNING id"
        )
        await write_audit(conn, entry(tid))
        await conn.execute("DELETE FROM tenants WHERE id = $1", tid)
        assert await conn.fetchval("SELECT count(*) FROM audit_log WHERE tenant_id = $1", tid) == 0
