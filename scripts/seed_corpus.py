"""Seed demo tenants, users and the corpus/ documents with per-folder ACLs.

Document slugs are deterministic: "<folder>-<file stem>", e.g. "hr-leave-policy"
(CLAUDE.md correction F). Re-running replaces documents by slug and removes stale ones.
"""

import asyncio
import json
import logging
import statistics
import sys
import time
from pathlib import Path
from uuid import UUID

import asyncpg

from gateway.config import get_settings
from gateway.db import assert_embedding_dim, assert_migrations_applied, create_pool
from gateway.ingest.embedder import Embedder
from gateway.ingest.pipeline import ingest_document

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"
SUPPORTED = {".md", ".markdown", ".txt", ".docx", ".pdf"}


async def upsert_tenant(conn: asyncpg.Connection, slug: str, name: str) -> UUID:
    tenant_id: UUID = await conn.fetchval(
        """
        INSERT INTO tenants (slug, name) VALUES ($1, $2)
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        slug,
        name,
    )
    return tenant_id


async def upsert_user(conn: asyncpg.Connection, tenant_id: UUID, user: dict[str, object]) -> None:
    await conn.execute(
        """
        INSERT INTO users (tenant_id, email, roles, clearance) VALUES ($1, $2, $3, $4)
        ON CONFLICT (tenant_id, email) DO UPDATE SET roles = EXCLUDED.roles, clearance = EXCLUDED.clearance
        """,
        tenant_id,
        user["email"],
        user["roles"],
        user["clearance"],
    )


async def main() -> None:
    settings = get_settings()
    manifest = json.loads((CORPUS_DIR / "tenants.json").read_text(encoding="utf-8"))
    folders: dict[str, dict[str, object]] = manifest["folders"]

    embedder = Embedder(
        settings.embedding_model_id,
        settings.embedding_dim,
        settings.embedding_cache_dir,
        settings.embedding_batch_size,
    )
    pool = await create_pool(settings.database_dsn)
    started = time.perf_counter()
    token_counts: list[int] = []
    doc_total = 0
    try:
        async with pool.acquire() as conn:
            await assert_migrations_applied(conn)
            await assert_embedding_dim(conn, embedder.dim, settings.embedding_dim)

        for tenant in manifest["tenants"]:
            async with pool.acquire() as conn:
                tenant_id = await upsert_tenant(conn, tenant["slug"], tenant["name"])
                for user in tenant["users"]:
                    await upsert_user(conn, tenant_id, user)

            seen: list[str] = []
            for folder, acl in folders.items():
                for path in sorted((CORPUS_DIR / tenant["slug"] / folder).glob("*")):
                    if path.suffix.lower() not in SUPPORTED:
                        continue
                    slug = f"{folder}-{path.stem}"
                    result = await ingest_document(
                        pool,
                        embedder,
                        settings,
                        tenant_id=tenant_id,
                        slug=slug,
                        path=path,
                        allowed_roles=acl["allowed_roles"],  # type: ignore[arg-type]
                        min_clearance=acl["min_clearance"],  # type: ignore[arg-type]
                        doc_metadata={"folder": folder},
                    )
                    seen.append(slug)
                    token_counts.extend(result.token_counts)
                    print(f"  {tenant['slug']}/{slug}: {len(result.token_counts)} chunks  ({result.title})")

            async with pool.acquire() as conn:
                removed = await conn.fetchval(
                    """
                    WITH d AS (DELETE FROM documents WHERE tenant_id = $1 AND NOT (slug = ANY($2::text[]))
                               RETURNING 1)
                    SELECT count(*) FROM d
                    """,
                    tenant_id,
                    seen,
                )
            doc_total += len(seen)
            print(
                f"tenant {tenant['slug']}: {len(seen)} documents, "
                f"{len(tenant['users'])} users, {removed} stale removed"
            )
    finally:
        await pool.close()

    if not token_counts:
        sys.exit("no chunks ingested")
    print()
    print(f"documents ingested : {doc_total}")
    print(f"chunks             : {len(token_counts)}")
    print(
        "tokens per chunk   : "
        f"min {min(token_counts)}, median {statistics.median(token_counts):.0f}, "
        f"mean {statistics.mean(token_counts):.0f}, max {max(token_counts)} "
        f"(hard max {settings.chunk_max_tokens}, model max {embedder.max_seq_len})"
    )
    print(f"total tokens       : {sum(token_counts)}")
    print(f"elapsed            : {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
