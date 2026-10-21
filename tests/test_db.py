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
    assert versions == ["001_init", "005_metrics", "006_query_log_answer", "007_query_log_prompt_version"]


async def test_phase1_tables_exist_and_later_phase_tables_do_not(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        for table in ("tenants", "users", "documents", "chunks", "query_log"):
            assert await conn.fetchval("SELECT to_regclass($1)", table) is not None
        for table in ("audit_log", "semantic_cache", "entities", "relations", "chunk_acl"):
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
