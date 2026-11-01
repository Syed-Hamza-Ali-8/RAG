"""Reciprocal Rank Fusion and hybrid retrieval over the seeded corpus."""

from uuid import UUID, uuid4

import asyncpg

from gateway.deps import auth_for_email
from gateway.ingest.embedder import Embedder
from gateway.retrieval.hybrid import HybridConfig, hybrid_search, rrf
from gateway.retrieval.vector import vector_search

A, B, C, D = (uuid4() for _ in range(4))


def test_rrf_sums_reciprocal_ranks() -> None:
    # A: 1/61 + 1/62; B: 1/62 + 1/61 (tie with A, broken by best rank, then id); C: 1/63; D: 1/63.
    fused = rrf([[A, B, C], [B, A, D]], k=60)
    assert set(fused[:2]) == {A, B} and set(fused[2:]) == {C, D}
    assert rrf([[A], [A]], 60) == [A]


def test_rrf_prefers_agreement_over_a_single_top_rank() -> None:
    # B is 2nd in both lists; A is 1st in one list only: 2/62 > 1/61.
    assert rrf([[A, B], [C, B]], k=60)[0] == B


def test_rrf_is_deterministic_on_ties() -> None:
    assert rrf([[A], [B]], 60) == rrf([[A], [B]], 60) == sorted([A, B], key=str)


async def test_hybrid_returns_permitted_chunks_only_and_at_most_top_k(
    pool: asyncpg.Pool, embedder: Embedder, corpus: dict[str, UUID]
) -> None:
    q = "What is the minimum monthly salary for a Manager (C1) in Karachi?"
    async with pool.acquire() as conn:
        auth = await auth_for_email(conn, "acme", "engineer@acme.example")
        hits = await hybrid_search(
            conn,
            acl_filter=auth.acl(),
            question=q,
            query_embedding=await embedder.embed_query(q),
            top_k=6,
            config=HybridConfig(),
        )
    assert 0 < len(hits) <= 6 and len({h.chunk_id for h in hits}) == len(hits)
    assert not any(h.document_slug == "hr-salary-bands" for h in hits)


async def test_hybrid_lifts_a_rare_term_chunk_that_vector_ranks_low(
    pool: asyncpg.Pool, embedder: Embedder, corpus: dict[str, UUID]
) -> None:
    # Golden q023: the Hajj paragraph lives in a large mixed-topic chunk that vector search ranks outside
    # the top 10; the rare word "Hajj" lets the keyword path find it.
    q = "How much Hajj leave can an Acme employee take, and after how much service?"
    async with pool.acquire() as conn:
        # q023's seeded user: the chunk is HR-only
        auth = await auth_for_email(conn, "acme", "hr@acme.example")
        vec = await embedder.embed_query(q)
        v = await vector_search(conn, acl_filter=auth.acl(), query_embedding=vec, top_k=10)
        h = await hybrid_search(
            conn, acl_filter=auth.acl(), question=q, query_embedding=vec, top_k=10, config=HybridConfig()
        )
    gold = ("hr-leave-policy", 1)
    assert gold not in [(c.document_slug, c.ordinal) for c in v]
    assert gold in [(c.document_slug, c.ordinal) for c in h]
