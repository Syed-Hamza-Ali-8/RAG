"""End-to-end tests of POST /v1/query against a real Postgres and the real embedder, with a stub LLM."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from pydantic import SecretStr

from gateway.config import Settings
from gateway.ingest.embedder import Embedder
from gateway.ingest.pipeline import ingest_document
from gateway.llm.prompts import PROMPT_VERSION, REFUSAL_MESSAGE
from gateway.main import create_app
from gateway.security.tokens import issue_token
from tests.conftest import StubLLM

ALPHA_DOC = """# Leave Policy

## Annual Leave

Full-time employees at Alpha receive 22 working days of paid annual leave per year.

## Sick Leave

Alpha employees receive 10 days of paid sick leave.
"""

BETA_DOC = """# Leave Policy

## Annual Leave

Full-time employees at Beta receive 30 working days of paid annual leave per year.
"""


# One ordinary user per test tenant; every request is made as that user with a bearer token.
USERS: dict[str, UUID] = {}
HEADERS: dict[str, dict[str, str]] = {}


async def ask(client: httpx.AsyncClient, as_tenant: str, question: str, /, **extra: object) -> httpx.Response:
    return await client.post("/v1/query", json={"question": question, **extra}, headers=HEADERS[as_tenant])


async def make_user(
    conn: asyncpg.Connection, tenant_id: UUID, email: str, roles: list[str], clearance: int
) -> UUID:
    user_id: UUID = await conn.fetchval(
        "INSERT INTO users (tenant_id, email, roles, clearance) VALUES ($1, $2, $3, $4) "
        "ON CONFLICT (tenant_id, email) DO UPDATE SET roles = $3, clearance = $4 RETURNING id",
        tenant_id,
        email,
        roles,
        clearance,
    )
    return user_id


async def make_tenant(conn: asyncpg.Connection, slug: str) -> UUID:
    tenant_id: UUID = await conn.fetchval(
        "INSERT INTO tenants (slug, name) VALUES ($1, $1) "
        "ON CONFLICT (slug) DO UPDATE SET name = $1 RETURNING id",
        slug,
    )
    return tenant_id


@pytest.fixture(scope="session")
async def seeded(
    pool: asyncpg.Pool, embedder: Embedder, settings: Settings, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, UUID]:
    d: Path = tmp_path_factory.mktemp("corpus")
    async with pool.acquire() as conn:
        ids = {slug: await make_tenant(conn, slug) for slug in ("alpha", "beta", "empty")}
        for slug, tenant_id in ids.items():
            USERS[slug] = await make_user(conn, tenant_id, f"staff@{slug}.example", ["employee"], 0)
            token = issue_token(settings, user_id=USERS[slug], tenant_id=tenant_id)
            HEADERS[slug] = {"Authorization": f"Bearer {token}"}
    for slug, text in (("alpha", ALPHA_DOC), ("beta", BETA_DOC)):
        path = d / f"{slug}-leave.md"
        path.write_text(text, encoding="utf-8")
        await ingest_document(
            pool, embedder, settings, tenant_id=ids[slug], slug="hr-leave-policy", path=path
        )
    return ids


@pytest.fixture
async def client(
    settings: Settings, seeded: dict[str, UUID], stub_llm: StubLLM
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, llm=stub_llm)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def query_log_rows(pool: asyncpg.Pool, tenant_id: UUID) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM query_log WHERE tenant_id = $1 ORDER BY id", tenant_id)


async def test_answer_has_citation_with_title_and_ordinal(
    client: httpx.AsyncClient, stub_llm: StubLLM, pool: asyncpg.Pool, seeded: dict[str, UUID]
) -> None:
    before = len(await query_log_rows(pool, seeded["alpha"]))
    r = await ask(client, "alpha", "How much annual leave do I get?")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refused"] is False
    assert body["answer"] == "Answer [S1]."
    (citation,) = body["citations"]
    assert citation["document_title"] == "Leave Policy"
    assert citation["document_slug"] == "hr-leave-policy"
    assert isinstance(citation["chunk_ordinal"], int)
    assert "22 working days" in str(stub_llm.calls[0][1]["content"])

    rows = await query_log_rows(pool, seeded["alpha"])
    assert len(rows) == before + 1
    row = rows[-1]
    assert row["refused"] is False
    assert row["model_used"] == "stub-model"
    assert row["route_tier"] == "small"
    assert row["total_ms"] >= row["retrieval_ms"] >= 0
    assert row["cache_hit"] is None and row["est_cost_usd"] is None and row["complexity_score"] is None
    assert row["answer_raw"] == "Answer [S1]."
    assert row["prompt_version"] == PROMPT_VERSION
    assert (row["citations_valid"], row["citations_rejected"]) == (1, 0)


async def test_retrieval_is_tenant_scoped(client: httpx.AsyncClient, stub_llm: StubLLM) -> None:
    r = await ask(client, "beta", "How much annual leave?")
    assert r.status_code == 200
    prompt = str(stub_llm.calls[0][1]["content"])
    assert "30 working days" in prompt
    assert "22 working days" not in prompt and "Alpha" not in prompt


async def test_zero_valid_citations_is_refused(
    client: httpx.AsyncClient, stub_llm: StubLLM, pool: asyncpg.Pool, seeded: dict[str, UUID]
) -> None:
    stub_llm.reply = lambda _: "Everyone gets 40 days [S9]."
    r = await ask(client, "alpha", "How much annual leave?")
    body = r.json()
    assert body["refused"] is True
    assert body["answer"] == REFUSAL_MESSAGE
    assert body["citations"] == []
    row = (await query_log_rows(pool, seeded["alpha"]))[-1]
    assert row["refused"] is True
    assert row["answer_raw"] == "Everyone gets 40 days [S9]."  # the rejected output is kept for diagnosis
    assert (row["citations_valid"], row["citations_rejected"]) == (0, 1)


async def test_lenticular_citation_is_accepted_and_normalised(
    client: httpx.AsyncClient, stub_llm: StubLLM, pool: asyncpg.Pool, seeded: dict[str, UUID]
) -> None:
    raw = "Full-time employees receive **22 working days**【S1】"
    stub_llm.reply = lambda _: raw
    r = await ask(client, "alpha", "How much annual leave?")
    body = r.json()
    assert body["refused"] is False
    assert body["answer"] == "Full-time employees receive **22 working days**[S1]"
    assert [c["label"] for c in body["citations"]] == ["S1"]
    row = (await query_log_rows(pool, seeded["alpha"]))[-1]
    assert row["answer_raw"] == raw  # stored exactly as the model wrote it
    assert (row["citations_valid"], row["citations_rejected"]) == (1, 0)


async def test_empty_tenant_refuses_without_calling_llm(
    client: httpx.AsyncClient, stub_llm: StubLLM, pool: asyncpg.Pool, seeded: dict[str, UUID]
) -> None:
    r = await ask(client, "empty", "Anything?")
    assert r.json()["refused"] is True
    assert stub_llm.calls == []
    row = (await query_log_rows(pool, seeded["empty"]))[-1]
    assert row["answer_raw"] is None and row["citations_valid"] is None and row["citations_rejected"] is None
    assert row["prompt_version"] is None  # no LLM call, so no prompt was used


async def test_missing_or_invalid_token_is_401(client: httpx.AsyncClient, settings: Settings) -> None:
    assert (await client.post("/v1/query", json={"question": "x"})).status_code == 401
    bad = {"Authorization": "Bearer not-a-token"}
    r = await client.post("/v1/query", json={"question": "x"}, headers=bad)
    assert r.status_code == 401 and r.json() == {"error": "unauthenticated"}
    forged = issue_token(
        settings.model_copy(update={"jwt_secret": SecretStr("a-different-secret-of-at-least-32-bytes")}),
        user_id=USERS["alpha"],
        tenant_id=uuid4(),
    )
    r = await client.post("/v1/query", json={"question": "x"}, headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_expired_token_is_401(
    client: httpx.AsyncClient, settings: Settings, seeded: dict[str, UUID]
) -> None:
    from datetime import UTC, datetime, timedelta

    old = issue_token(
        settings, user_id=USERS["alpha"], tenant_id=seeded["alpha"], now=datetime.now(UTC) - timedelta(days=1)
    )
    r = await client.post("/v1/query", json={"question": "x"}, headers={"Authorization": f"Bearer {old}"})
    assert r.status_code == 401


async def test_token_for_deleted_user_is_401(
    client: httpx.AsyncClient, settings: Settings, pool: asyncpg.Pool, seeded: dict[str, UUID]
) -> None:
    async with pool.acquire() as conn:
        ghost = await make_user(conn, seeded["alpha"], "ghost@alpha.example", ["employee"], 0)
    token = issue_token(settings, user_id=ghost, tenant_id=seeded["alpha"])
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE id = $1", ghost)
    r = await client.post("/v1/query", json={"question": "x"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_body_tenant_is_rejected_even_when_it_matches(client: httpx.AsyncClient) -> None:
    assert (await ask(client, "alpha", "How much annual leave?", tenant="alpha")).status_code == 422
    assert (await ask(client, "alpha", "How much annual leave?", tenant="beta")).status_code == 422


async def test_every_query_writes_one_audit_row(
    client: httpx.AsyncClient, pool: asyncpg.Pool, seeded: dict[str, UUID]
) -> None:
    async with pool.acquire() as conn:
        before = await conn.fetchval("SELECT coalesce(max(id), 0) FROM audit_log")
    r = await ask(client, "alpha", "How much annual leave?")
    assert r.status_code == 200
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM audit_log WHERE id > $1", before)
        log_tenant = await conn.fetchval(
            "SELECT tenant_id FROM query_log WHERE id = $1", rows[0]["query_log_id"]
        )
    (row,) = rows
    assert (row["tenant_id"], row["user_id"]) == (seeded["alpha"], USERS["alpha"])
    assert list(row["user_roles"]) == ["employee"] and row["user_clearance"] == 0
    assert row["query_text"] == "How much annual leave?" and row["retrieved_ids"]
    assert row["served_from_cache"] is False and len(row["answer_hash"]) == 64
    assert log_tenant == seeded["alpha"]


async def test_dev_token_issuer(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/auth/token", json={"tenant": "alpha", "email": "staff@alpha.example"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    q = await client.post(
        "/v1/query", json={"question": "How much annual leave?"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert q.status_code == 200
    # Unknown tenant and unknown email look the same: no user enumeration.
    assert (await client.post("/v1/auth/token", json={"tenant": "nope", "email": "x@y.z"})).status_code == 401
    assert (
        await client.post("/v1/auth/token", json={"tenant": "alpha", "email": "x@y.z"})
    ).status_code == 401


async def test_dev_token_issuer_is_off_unless_enabled(settings: Settings, seeded: dict[str, UUID]) -> None:
    app = create_app(settings.model_copy(update={"auth_dev_issuer_enabled": False}), llm=StubLLM())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/v1/auth/token", json={"tenant": "alpha", "email": "staff@alpha.example"})
    assert r.status_code == 404


async def test_rate_limit_exhausted_is_503_not_a_fake_answer(
    client: httpx.AsyncClient, stub_llm: StubLLM
) -> None:
    from gateway.errors import RateLimitExhausted

    def boom(_: object) -> str:
        raise RateLimitExhausted("HTTP 429 after 5 attempts")

    stub_llm.reply = boom
    r = await ask(client, "alpha", "How much annual leave?")
    assert r.status_code == 503
    assert r.json()["error"] == "llm_rate_limited"


async def test_request_validation(client: httpx.AsyncClient) -> None:
    assert (await ask(client, "alpha", "")).status_code == 422
    assert (await ask(client, "alpha", "q", top_k=99)).status_code == 422


async def test_rate_limit_response_does_not_leak_provider_detail(
    client: httpx.AsyncClient, stub_llm: StubLLM
) -> None:
    from gateway.errors import RateLimitExhausted

    def boom(_: object) -> str:
        raise RateLimitExhausted(
            "HTTP 429 after 5 attempts",
            provider_message="Rate limit reached in organization org_SECRETORG on tokens per minute",
            rate_limit_headers={"x-ratelimit-remaining-tokens": "0"},
        )

    stub_llm.reply = boom
    r = await ask(client, "alpha", "How much annual leave?")
    assert r.status_code == 503
    assert r.json() == {"error": "llm_rate_limited", "detail": "HTTP 429 after 5 attempts"}
    assert "org_SECRETORG" not in r.text
