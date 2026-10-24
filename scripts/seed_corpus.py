"""Seed demo tenants, users and the corpus/ documents with per-folder ACLs (see gateway.ingest.seed)."""

import asyncio
import logging
import statistics
import sys
import time

from gateway.config import get_settings
from gateway.db import assert_embedding_dim, assert_migrations_applied, create_pool
from gateway.ingest.embedder import Embedder
from gateway.ingest.seed import seed_corpus


async def main() -> None:
    settings = get_settings()
    embedder = Embedder(
        settings.embedding_model_id,
        settings.embedding_dim,
        settings.embedding_cache_dir,
        settings.embedding_batch_size,
    )
    pool = await create_pool(settings.database_dsn)
    started = time.perf_counter()
    try:
        async with pool.acquire() as conn:
            await assert_migrations_applied(conn)
            await assert_embedding_dim(conn, embedder.dim, settings.embedding_dim)
        result = await seed_corpus(pool, embedder, settings, progress=print)
    finally:
        await pool.close()

    token_counts = result.token_counts
    if not token_counts:
        sys.exit("no chunks ingested")
    print()
    print(f"documents ingested : {result.documents}")
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
