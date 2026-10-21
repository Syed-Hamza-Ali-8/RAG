"""asyncpg pool, migration runner and schema checks."""

import logging
from pathlib import Path

import asyncpg
from pgvector.asyncpg import register_vector

from gateway.errors import EmbeddingDimensionMismatch, MigrationsNotApplied

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
# Arbitrary constant; serialises concurrent migrate runs.
_MIGRATION_LOCK_ID = 7_340_001


async def create_pool(dsn: str, *, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size, init=register_vector)
    assert pool is not None
    return pool


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(directory.glob("*.sql"))


async def apply_migrations(conn: asyncpg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply unapplied migrations in filename order. Returns the versions applied."""
    await conn.execute("SELECT pg_advisory_lock($1)", _MIGRATION_LOCK_ID)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        done = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
        applied: list[str] = []
        for path in migration_files(directory):
            version = path.stem
            if version in done:
                continue
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", version)
            log.info("applied migration %s", version)
            applied.append(version)
        return applied
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", _MIGRATION_LOCK_ID)


async def assert_migrations_applied(conn: asyncpg.Connection, directory: Path = MIGRATIONS_DIR) -> None:
    expected = {p.stem for p in migration_files(directory)}
    exists = await conn.fetchval("SELECT to_regclass('schema_migrations') IS NOT NULL")
    done = (
        {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")} if exists else set()
    )
    missing = sorted(expected - done)
    if missing:
        raise MigrationsNotApplied(f"unapplied migrations: {missing}; run `uv run python scripts/migrate.py`")


async def embedding_column_dim(conn: asyncpg.Connection) -> int:
    # For pgvector's `vector(n)`, atttypmod holds n.
    dim = await conn.fetchval(
        """
        SELECT atttypmod FROM pg_attribute
        WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'
        """
    )
    return int(dim)


async def assert_embedding_dim(conn: asyncpg.Connection, model_dim: int, configured_dim: int) -> None:
    column_dim = await embedding_column_dim(conn)
    if not (model_dim == configured_dim == column_dim):
        raise EmbeddingDimensionMismatch(
            f"embedding dims disagree: model outputs {model_dim}, EMBEDDING_DIM={configured_dim}, "
            f"chunks.embedding is vector({column_dim})"
        )
