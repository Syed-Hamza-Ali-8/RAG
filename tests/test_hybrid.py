"""Reciprocal Rank Fusion and hybrid retrieval over the seeded corpus."""

from uuid import UUID, uuid4

import asyncpg

from gateway.config import Settings
from gateway.deps import auth_for_email
from gateway.ingest.embedder import Embedder
from gateway.retrieval.hybrid import HybridConfig, config_from, hybrid_search, rrf
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


async def test_gate_keeps_a_single_hop_question_off_the_graph_path(
    pool: asyncpg.Pool, embedder: Embedder, corpus: dict[str, UUID]
) -> None:
    # A short single-hop question scores below the gate: the graph path does not run, and the result is
    # exactly the vector+FTS result (gated fusion cannot change single-hop retrieval).
    q = "What is Acme's annual leave entitlement?"
    async with pool.acquire() as conn:
        auth = await auth_for_email(conn, "acme", "employee@acme.example")
        vec = await embedder.embed_query(q)
        trace: dict[str, object] = {}
        gated = await hybrid_search(
            conn,
            acl_filter=auth.acl(),
            question=q,
            query_embedding=vec,
            top_k=6,
            config=HybridConfig(graph=True, graph_gate=0.38),
            trace=trace,
        )
        plain = await hybrid_search(
            conn, acl_filter=auth.acl(), question=q, query_embedding=vec, top_k=6, config=HybridConfig()
        )
    assert trace["graph"] is False and float(trace["gate_score"]) < 0.38  # type: ignore[arg-type]
    assert [c.chunk_id for c in gated] == [c.chunk_id for c in plain]


async def test_gate_opens_for_a_multi_hop_question(
    pool: asyncpg.Pool, embedder: Embedder, corpus: dict[str, UUID]
) -> None:
    q = "Which provider hosts Marlowe Retail Group's files, and what monthly availability does it commit to?"
    async with pool.acquire() as conn:
        auth = await auth_for_email(conn, "globex", "legal@globex.example")
        trace: dict[str, object] = {}
        await hybrid_search(
            conn,
            acl_filter=auth.acl(),
            question=q,
            query_embedding=await embedder.embed_query(q),
            top_k=6,
            config=HybridConfig(graph=True, graph_gate=0.38),
            trace=trace,
        )
    assert trace["graph"] is True and float(trace["gate_score"]) >= 0.38  # type: ignore[arg-type]


def test_config_from_maps_every_retrieval_mode(settings: Settings) -> None:
    def cfg(mode: str) -> HybridConfig | None:
        return config_from(settings.model_copy(update={"retrieval_mode": mode}))

    assert cfg("vector") is None
    assert cfg("hybrid") == HybridConfig(rrf_k=60, depth=20, graph=False, graph_gate=None)
    assert cfg("hybrid_graph") == HybridConfig(graph=True, graph_gate=None)
    assert cfg("hybrid_graph_gated") == HybridConfig(graph=True, graph_gate=0.38)
