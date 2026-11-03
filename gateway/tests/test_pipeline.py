from pathlib import Path

import asyncpg

from gateway.config import Settings
from gateway.ingest.embedder import Embedder
from gateway.ingest.pipeline import ingest_document


async def test_reingest_replaces_by_slug_and_stores_acl(
    pool: asyncpg.Pool, embedder: Embedder, settings: Settings, tmp_path: Path
) -> None:
    async with pool.acquire() as conn:
        tenant_id = await conn.fetchval(
            "INSERT INTO tenants (slug, name) VALUES ('pipe', 'Pipe') RETURNING id"
        )
    path = tmp_path / "salary.md"
    path.write_text("# Salary Bands\n\n## Grades\n\nAnalyst band is 100 to 200.\n", encoding="utf-8")

    first = await ingest_document(
        pool,
        embedder,
        settings,
        tenant_id=tenant_id,
        slug="hr-salary-bands",
        path=path,
        allowed_roles=["hr"],
        min_clearance=2,
    )
    second = await ingest_document(
        pool,
        embedder,
        settings,
        tenant_id=tenant_id,
        slug="hr-salary-bands",
        path=path,
        allowed_roles=["hr"],
        min_clearance=2,
    )
    assert first.document_id != second.document_id

    async with pool.acquire() as conn:
        docs = await conn.fetchval("SELECT count(*) FROM documents WHERE tenant_id = $1", tenant_id)
        rows = await conn.fetch(
            "SELECT ordinal, heading_path, allowed_roles, min_clearance, token_count FROM chunks "
            "WHERE tenant_id = $1 ORDER BY ordinal",
            tenant_id,
        )
    assert docs == 1
    assert [r["ordinal"] for r in rows] == list(range(len(rows)))
    assert rows[0]["heading_path"] == "Salary Bands > Grades"
    assert all(r["allowed_roles"] == ["hr"] and r["min_clearance"] == 2 for r in rows)
    assert [r["token_count"] for r in rows] == second.token_counts
