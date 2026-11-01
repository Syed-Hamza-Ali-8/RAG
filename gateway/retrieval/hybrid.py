"""Hybrid retrieval (Phase 5, M1): vector and keyword paths fused with Reciprocal Rank Fusion.

Each path is ACL-filtered in its own SQL; fusion only reorders what both already permitted. Constants fixed
by the Phase 5 pre-registration, not tuned on the golden set: RRF k = 60, each path contributes its top 20.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import asyncpg

from gateway.retrieval.graph import graph_search
from gateway.retrieval.keyword import keyword_search
from gateway.retrieval.vector import RetrievedChunk, vector_search
from gateway.security import acl


@dataclass(frozen=True)
class HybridConfig:
    rrf_k: int = 60
    depth: int = 20  # candidates each path contributes
    graph: bool = False  # Phase 5 M2: the graph path as a third RRF input
    graph_depth: int = 2  # walk depth cap (correction M)
    graph_seeds: int = 6  # the fused vector+keyword top-n whose entities seed the walk


def rrf(rankings: Sequence[Sequence[UUID]], k: int) -> list[UUID]:
    """Fuse ranked id lists: score(d) = sum over lists of 1 / (k + rank), ranks from 1. Ties break by the best
    rank any list gave the item, then by id, so the order is deterministic."""
    score: dict[UUID, float] = {}
    best: dict[UUID, int] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            score[item] = score.get(item, 0.0) + 1.0 / (k + rank)
            best[item] = min(best.get(item, rank), rank)
    return sorted(score, key=lambda i: (-score[i], best[i], str(i)))


async def hybrid_search(
    conn: asyncpg.Connection,
    *,
    acl_filter: acl.AclFilter,
    question: str,
    query_embedding: list[float],
    top_k: int,
    config: HybridConfig,
) -> list[RetrievedChunk]:
    depth = max(config.depth, top_k)
    vec = await vector_search(conn, acl_filter=acl_filter, query_embedding=query_embedding, top_k=depth)
    kw = await keyword_search(
        conn, acl_filter=acl_filter, question=question, query_embedding=query_embedding, top_k=depth
    )
    by_id = {c.chunk_id: c for c in (*vec, *kw)}
    rankings = [[c.chunk_id for c in vec], [c.chunk_id for c in kw]]
    fused = rrf(rankings, config.rrf_k)
    if config.graph:
        walked = await graph_search(
            conn,
            acl_filter=acl_filter,
            seed_chunk_ids=fused[: config.graph_seeds],
            query_embedding=query_embedding,
            max_depth=config.graph_depth,
            top_k=depth,
        )
        by_id.update({c.chunk_id: c for c in walked})
        fused = rrf([*rankings, [c.chunk_id for c in walked]], config.rrf_k)
    return [by_id[i] for i in fused[:top_k]]
