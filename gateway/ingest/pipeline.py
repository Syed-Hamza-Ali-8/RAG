"""load → chunk → embed → store, in one transaction per document."""

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import asyncpg

from gateway.config import Settings
from gateway.errors import DocumentLoadError
from gateway.ingest.chunker import chunk_sections
from gateway.ingest.embedder import Embedder
from gateway.ingest.loaders import load_document

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestResult:
    document_id: UUID
    slug: str
    title: str
    token_counts: list[int]


async def ingest_document(
    pool: asyncpg.Pool,
    embedder: Embedder,
    settings: Settings,
    *,
    tenant_id: UUID,
    slug: str,
    path: Path,
    allowed_roles: Sequence[str] = (),
    min_clearance: int = 0,
    doc_metadata: dict[str, object] | None = None,
) -> IngestResult:
    """Ingest one file. An existing document with the same (tenant, slug) is replaced."""
    doc = load_document(path)
    chunks = chunk_sections(
        doc.sections,
        embedder,
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
    )
    if not chunks:
        raise DocumentLoadError(f"{path}: produced no chunks")
    vectors = await embedder.embed_passages([c.embed_text for c in chunks])

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM documents WHERE tenant_id = $1 AND slug = $2", tenant_id, slug)
        document_id: UUID = await conn.fetchval(
            """
            INSERT INTO documents (tenant_id, slug, title, source_uri, mime_type, doc_metadata)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            RETURNING id
            """,
            tenant_id,
            slug,
            doc.title,
            path.as_posix(),
            doc.mime_type,
            json.dumps(doc_metadata or {}),
        )
        await conn.executemany(
            """
            INSERT INTO chunks (tenant_id, document_id, ordinal, content, heading_path,
                                token_count, embedding, allowed_roles, min_clearance)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            [
                (
                    tenant_id,
                    document_id,
                    c.ordinal,
                    c.content,
                    c.heading_path,
                    c.token_count,
                    vec,
                    list(allowed_roles),
                    min_clearance,
                )
                for c, vec in zip(chunks, vectors, strict=True)
            ],
        )
    log.info("ingested %s: %d chunks", slug, len(chunks))
    return IngestResult(document_id, slug, doc.title, [c.token_count for c in chunks])
