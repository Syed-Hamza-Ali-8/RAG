"""Seed demo tenants, users and the corpus/ documents with per-folder ACLs.

Document slugs are deterministic: "<folder>-<file stem>", e.g. "hr-leave-policy" (CLAUDE.md
correction F). Re-running replaces documents by slug and removes stale ones. Used by
scripts/seed_corpus.py and by the ACL isolation suite, which seeds the real corpus into the test
database through this same code.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import asyncpg

from gateway.config import Settings
from gateway.ingest.embedder import Embedder
from gateway.ingest.pipeline import ingest_document

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus"
SUPPORTED = {".md", ".markdown", ".txt", ".docx", ".pdf"}


@dataclass
class SeedResult:
    documents: int = 0
    users: int = 0
    stale_removed: int = 0
    token_counts: list[int] = field(default_factory=list)


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


async def seed_corpus(
    pool: asyncpg.Pool,
    embedder: Embedder,
    settings: Settings,
    corpus_dir: Path = CORPUS_DIR,
    progress: Callable[[str], None] | None = None,
) -> SeedResult:
    manifest = json.loads((corpus_dir / "tenants.json").read_text(encoding="utf-8"))
    folders: dict[str, dict[str, object]] = manifest["folders"]
    result = SeedResult()
    for tenant in manifest["tenants"]:
        async with pool.acquire() as conn:
            tenant_id = await upsert_tenant(conn, tenant["slug"], tenant["name"])
            for user in tenant["users"]:
                await upsert_user(conn, tenant_id, user)
        result.users += len(tenant["users"])

        seen: list[str] = []
        for folder, acl in folders.items():
            for path in sorted((corpus_dir / tenant["slug"] / folder).glob("*")):
                if path.suffix.lower() not in SUPPORTED:
                    continue
                slug = f"{folder}-{path.stem}"
                ingested = await ingest_document(
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
                result.token_counts.extend(ingested.token_counts)
                if progress:
                    progress(
                        f"  {tenant['slug']}/{slug}: {len(ingested.token_counts)} chunks  ({ingested.title})"
                    )

        async with pool.acquire() as conn:
            removed: int = await conn.fetchval(
                """
                WITH d AS (DELETE FROM documents WHERE tenant_id = $1 AND NOT (slug = ANY($2::text[]))
                           RETURNING 1)
                SELECT count(*) FROM d
                """,
                tenant_id,
                seen,
            )
        result.documents += len(seen)
        result.stale_removed += removed
        if progress:
            progress(
                f"tenant {tenant['slug']}: {len(seen)} documents, {len(tenant['users'])} users, "
                f"{removed} stale removed"
            )
    return result
