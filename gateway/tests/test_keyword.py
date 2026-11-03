"""Keyword (Postgres FTS) path over the seeded corpus: recall of rare terms, OR semantics, ACL in SQL."""

from uuid import UUID

import asyncpg
import pytest

from gateway.deps import auth_for_email
from gateway.ingest.embedder import Embedder
from gateway.retrieval import keyword
from gateway.retrieval.keyword import keyword_search
from gateway.security.acl import acl_predicate


async def _search(pool: asyncpg.Pool, embedder: Embedder, email: str, question: str, k: int = 10) -> list:
    async with pool.acquire() as conn:
        auth = await auth_for_email(conn, "acme", email)
        return await keyword_search(
            conn,
            acl_filter=auth.acl(),
            question=question,
            query_embedding=await embedder.embed_query(question),
            top_k=k,
        )


async def test_a_rare_term_finds_its_chunk(
    pool: asyncpg.Pool, embedder: Embedder, corpus: dict[str, UUID]
) -> None:
    hits = await _search(pool, embedder, "hr@acme.example", "How much Hajj leave can an Acme employee take?")
    assert hits and any("Hajj" in h.content for h in hits[:3])
    assert all(-1.0 <= h.score <= 1.0 for h in hits)  # cosine similarity, not an FTS rank


async def test_a_full_sentence_question_still_matches(
    pool: asyncpg.Pool, embedder: Embedder, corpus: dict[str, UUID]
) -> None:
    # OR of lexemes: an AND of every word in a long question would match nothing.
    q = "Which runbook step failed during the March 2026 Atlas outage, and what setting must be used now?"
    assert await _search(pool, embedder, "engineer@acme.example", q)


async def test_stopword_only_question_returns_nothing(
    pool: asyncpg.Pool, embedder: Embedder, corpus: dict[str, UUID]
) -> None:
    assert await _search(pool, embedder, "hr@acme.example", "what is the and of it?") == []


async def test_keyword_path_filters_acls_in_sql(
    pool: asyncpg.Pool, embedder: Embedder, corpus: dict[str, UUID]
) -> None:
    # The salary bands are HR-only (clearance 2): an engineer's keyword search must never return them.
    q = "minimum monthly salary Manager C1 Karachi salary bands"
    engineer = await _search(pool, embedder, "engineer@acme.example", q, k=20)
    hr = await _search(pool, embedder, "hr@acme.example", q, k=20)
    assert any(h.document_slug == "hr-salary-bands" for h in hr)
    assert not any(h.document_slug == "hr-salary-bands" for h in engineer)
    assert not any("650,000" in h.content for h in engineer)


def test_keyword_sql_carries_the_predicate() -> None:
    assert acl_predicate("c", 4) in keyword._keyword_sql()


@pytest.mark.parametrize("q", ["'; DROP TABLE chunks; --", "a & b | !c <-> d", "(((", ":*"])
async def test_tsquery_syntax_in_the_question_is_just_text(
    pool: asyncpg.Pool, embedder: Embedder, corpus: dict[str, UUID], q: str
) -> None:
    # The question is a bound parameter and passes through to_tsvector, never to_tsquery directly.
    await _search(pool, embedder, "hr@acme.example", q)
