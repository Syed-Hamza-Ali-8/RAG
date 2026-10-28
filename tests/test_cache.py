"""Semantic cache unit behaviour: signature, content key, bypass list, scoped lookup, TTL, triggers."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest
from verify_adversarial_cache import role_signature as reference_signature

from gateway.cache import semantic
from gateway.cache.semantic import CacheConfig, content_key, role_signature
from gateway.config import Settings
from gateway.models.query import Citation

GOLDEN = [json.loads(line) for line in open("eval/golden_set.jsonl", encoding="utf-8") if line.strip()]


@pytest.mark.parametrize(
    ("roles", "clearance"),
    [(["employee"], 0), (["employee", "hr"], 2), (["hr", "employee", "hr"], 2), (["legal", "finance"], 3)],
)
def test_role_signature_matches_the_pre_registered_definition(roles: list[str], clearance: int) -> None:
    assert role_signature(roles, clearance) == reference_signature(roles, clearance)


def test_role_signature_ignores_order_and_duplicates_but_not_clearance_or_roles() -> None:
    assert role_signature(("hr", "employee"), 2) == role_signature(("employee", "hr", "hr"), 2)
    assert role_signature(("employee", "hr"), 2) != role_signature(("employee", "hr"), 1)
    assert role_signature(("employee", "hr"), 2) != role_signature(("employee", "finance"), 2)


def test_content_key_separates_every_golden_near_miss_pair() -> None:
    pairs: dict[str, list[str]] = {}
    for g in GOLDEN:
        if g["type"] == "near_miss":
            pairs.setdefault(g["pair"], []).append(g["question"])
    assert len(pairs) == 5
    for pair, (a, b) in pairs.items():
        assert content_key(a) != content_key(b), pair


def test_content_key_is_stable_under_case_punctuation_order_and_stopwords() -> None:
    k = content_key("What is the contract reference for Ledgerline Software?")
    assert k == content_key("what is the contract reference for ledgerline software")
    assert k == content_key("WHAT IS THE CONTRACT REFERENCE FOR LEDGERLINE SOFTWARE!!")
    assert k == content_key("Ledgerline Software: what is the contract reference?")
    assert (
        content_key(f"Globex{chr(0x2019)}s per diem")
        == content_key("Globex's per diem")
        == content_key("globex per diem")
    )


def test_content_key_keeps_numbers_negations_and_comparatives() -> None:
    assert content_key("below 99.9% but at least 99.0%") != content_key("below 99.0%")
    assert content_key("claim of USD 2,000") != content_key("claim of USD 5,000")
    assert content_key("Is remote work allowed?") != content_key("Is remote work not allowed?")
    assert content_key("leave before the deadline") != content_key("leave after the deadline")


def test_bypass_list_catches_temporal_and_entity_qualifiers_only(settings: Settings) -> None:
    cfg = CacheConfig.from_patterns(0.95, 24, Settings.model_fields["cache_bypass_patterns"].default)
    for q in (
        "How much have we spent on cloud hosting this month?",
        "Which invoices are overdue as of today?",
        "What expenses can be billed for Client A?",
        "What is our current headcount?",
        "Who is currently on call?",
        "What is the latest version of the expense policy?",
        "What have we billed to date?",
        "What did we spend last quarter?",
        "What changed yesterday?",
        "Who is on call now?",
        "What is the rate for customer Marlowe?",
    ):
        assert cfg.bypassed(q), q
    for q in (
        "What is the contract reference for Ledgerline Software?",
        "How long is maternity leave at Acme?",
        # golden q024: "client-requested" is not a named client (a false positive of the first pattern)
        "How many days of time off in lieu can Acme consultants take for client-requested weekend work?",
    ):
        assert not cfg.bypassed(q), q


def test_lookup_sql_scopes_by_tenant_signature_and_content_words() -> None:
    sql = semantic._lookup_sql()
    assert "c.tenant_id = $1 AND c.role_signature = $2" in sql
    assert "c.content_key = $3" in sql and ">= $5" in sql and "c.expires_at > now()" in sql


def _citation() -> Citation:
    return Citation(
        label="S1",
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_slug="doc",
        document_title="Doc",
        chunk_ordinal=0,
        heading_path=None,
    )


@pytest.fixture
async def tenants(pool: asyncpg.Pool) -> tuple[UUID, UUID]:
    async with pool.acquire() as conn:
        ids = []
        for slug in ("cacheco", "cacheco2"):
            ids.append(
                await conn.fetchval(
                    "INSERT INTO tenants (slug, name) VALUES ($1, $1) "
                    "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                    slug,
                )
            )
        await conn.execute("DELETE FROM semantic_cache WHERE tenant_id = ANY($1::uuid[])", ids)
    return ids[0], ids[1]


VEC = [1.0] + [0.0] * 383


async def _store(conn: asyncpg.Connection, tenant: UUID, question: str, ttl_hours: int = 24) -> None:
    await semantic.store(
        conn,
        tenant_id=tenant,
        signature="sig",
        key=content_key(question),
        question=question,
        embedding=VEC,
        answer="cached",
        citations=[_citation()],
        model_used="m",
        ttl_hours=ttl_hours,
    )


async def _lookup(conn: asyncpg.Connection, tenant: UUID, question: str, sig: str = "sig") -> object:
    return await semantic.lookup(
        conn, tenant_id=tenant, signature=sig, key=content_key(question), embedding=VEC, threshold=0.95
    )


async def test_lookup_hits_only_in_scope_and_counts_hits(
    pool: asyncpg.Pool, tenants: tuple[UUID, UUID]
) -> None:
    a, b = tenants
    q = "What is the contract reference for Ledgerline Software?"
    async with pool.acquire() as conn:
        await _store(conn, a, q)
        assert await _lookup(conn, a, q) is not None
        assert await _lookup(conn, a, q.lower()) is not None
        assert await _lookup(conn, a, q, sig="other") is None
        assert await _lookup(conn, b, q) is None
        assert await _lookup(conn, a, "What is the contract reference for Fernbook Software?") is None
        assert await conn.fetchval("SELECT hit_count FROM semantic_cache WHERE tenant_id = $1", a) == 2


async def test_expired_entries_are_not_served(pool: asyncpg.Pool, tenants: tuple[UUID, UUID]) -> None:
    a, _ = tenants
    async with pool.acquire() as conn:
        await _store(conn, a, "How long is maternity leave?")
        await conn.execute(
            "UPDATE semantic_cache SET expires_at = $2 WHERE tenant_id = $1",
            a,
            datetime.now(UTC) - timedelta(seconds=1),
        )
        assert await _lookup(conn, a, "How long is maternity leave?") is None


async def test_store_refuses_an_answer_without_citations(
    pool: asyncpg.Pool, tenants: tuple[UUID, UUID]
) -> None:
    async with pool.acquire() as conn:
        with pytest.raises(ValueError):
            await semantic.store(
                conn,
                tenant_id=tenants[0],
                signature="sig",
                key="k",
                question="q",
                embedding=VEC,
                answer="x",
                citations=[],
                model_used="m",
                ttl_hours=24,
            )


@pytest.mark.parametrize(
    "change",
    [
        "INSERT INTO documents (tenant_id, slug, title) VALUES ($1, 'trigger-doc', 'T')",
        "UPDATE documents SET title = title WHERE tenant_id = $1",
        "UPDATE chunks SET min_clearance = min_clearance WHERE tenant_id = $1",
        "DELETE FROM documents WHERE tenant_id = $1",
    ],
)
async def test_any_document_or_chunk_change_wipes_only_that_tenants_cache(
    pool: asyncpg.Pool, tenants: tuple[UUID, UUID], change: str
) -> None:
    a, b = tenants
    async with pool.acquire() as conn:
        doc = await conn.fetchval(
            "INSERT INTO documents (tenant_id, slug, title) VALUES ($1, $2, 'D') RETURNING id",
            a,
            f"d-{uuid4()}",
        )
        await conn.execute(
            "INSERT INTO chunks (tenant_id, document_id, ordinal, content, token_count, embedding) "
            "VALUES ($1, $2, 0, 'x', 1, $3)",
            a,
            doc,
            VEC,
        )
        await _store(conn, a, "question one")
        await _store(conn, b, "question one")
        await conn.execute(change, a)
        assert await conn.fetchval("SELECT count(*) FROM semantic_cache WHERE tenant_id = $1", a) == 0
        assert await conn.fetchval("SELECT count(*) FROM semantic_cache WHERE tenant_id = $1", b) == 1
        await conn.execute("DELETE FROM documents WHERE tenant_id = $1", a)
