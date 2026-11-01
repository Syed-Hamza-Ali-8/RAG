import asyncpg
import pytest

from gateway.db import apply_migrations, assert_embedding_dim, assert_migrations_applied, migration_files
from gateway.errors import EmbeddingDimensionMismatch, MigrationsNotApplied


async def test_all_migrations_applied_and_rerun_is_noop(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await assert_migrations_applied(conn)
        assert await apply_migrations(conn) == []
        versions = [
            r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations ORDER BY 1")
        ]
    assert versions == [p.stem for p in migration_files()]
    assert versions == [
        "001_init",
        "002_audit_log",
        "003_cache",
        "005_metrics",
        "006_query_log_answer",
        "007_query_log_prompt_version",
        "008_query_log_purpose",
        "009_query_log_outcome",
        "010_query_log_cache_lookup",
        "011_chunks_fts",
    ]


async def test_phase4_tables_exist_and_later_phase_tables_do_not(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        for table in ("tenants", "users", "documents", "chunks", "query_log", "audit_log", "semantic_cache"):
            assert await conn.fetchval("SELECT to_regclass($1)", table) is not None
        for table in ("entities", "relations", "chunk_acl"):
            assert await conn.fetchval("SELECT to_regclass($1)", table) is None


async def test_unapplied_migration_is_detected(pool: asyncpg.Pool, tmp_path: object) -> None:
    from pathlib import Path

    d = Path(str(tmp_path))
    for p in migration_files():
        (d / p.name).write_text(p.read_text())
    (d / "999_future.sql").write_text("SELECT 1;")
    async with pool.acquire() as conn:
        with pytest.raises(MigrationsNotApplied, match="999_future"):
            await assert_migrations_applied(conn, d)


async def test_embedding_dim_check(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await assert_embedding_dim(conn, 384, 384)
        with pytest.raises(EmbeddingDimensionMismatch):
            await assert_embedding_dim(conn, 768, 768)


async def test_query_log_outcome_must_agree_with_refused(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        tid = await conn.fetchval(
            "INSERT INTO tenants (slug, name) VALUES ('outcomeco', 'OutcomeCo') "
            "ON CONFLICT (slug) DO UPDATE SET name = 'OutcomeCo' RETURNING id"
        )
        insert = (
            "INSERT INTO query_log (tenant_id, route_tier, retrieval_ms, total_ms, refused, outcome) "
            "VALUES ($1, 'small', 1, 1, $2, $3)"
        )
        for refused, outcome in ((True, "answered"), (False, "refused"), (True, "truncated")):
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(insert, tid, refused, outcome)
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(insert, tid, False, "partial")
        await conn.execute(insert, tid, False, "truncated")
