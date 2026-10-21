"""End-to-end tests of POST /v1/query against a real Postgres and the real embedder, with a stub LLM."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx
import pytest

from gateway.config import Settings
from gateway.ingest.embedder import Embedder
from gateway.ingest.pipeline import ingest_document
from gateway.llm.prompts import REFUSAL_MESSAGE
from gateway.main import create_app
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
    r = await client.post(
        "/v1/query", json={"tenant": "alpha", "question": "How much annual leave do I get?"}
    )
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


async def test_retrieval_is_tenant_scoped(client: httpx.AsyncClient, stub_llm: StubLLM) -> None:
    r = await client.post("/v1/query", json={"tenant": "beta", "question": "How much annual leave?"})
    assert r.status_code == 200
    prompt = str(stub_llm.calls[0][1]["content"])
    assert "30 working days" in prompt
    assert "22 working days" not in prompt and "Alpha" not in prompt


async def test_zero_valid_citations_is_refused(
    client: httpx.AsyncClient, stub_llm: StubLLM, pool: asyncpg.Pool, seeded: dict[str, UUID]
) -> None:
    stub_llm.reply = lambda _: "Everyone gets 40 days [S9]."
    r = await client.post("/v1/query", json={"tenant": "alpha", "question": "How much annual leave?"})
    body = r.json()
    assert body["refused"] is True
    assert body["answer"] == REFUSAL_MESSAGE
    assert body["citations"] == []
    assert (await query_log_rows(pool, seeded["alpha"]))[-1]["refused"] is True


async def test_empty_tenant_refuses_without_calling_llm(client: httpx.AsyncClient, stub_llm: StubLLM) -> None:
    r = await client.post("/v1/query", json={"tenant": "empty", "question": "Anything?"})
    assert r.json()["refused"] is True
    assert stub_llm.calls == []


async def test_unknown_tenant_is_404(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/query", json={"tenant": "nope", "question": "x"})
    assert r.status_code == 404


async def test_rate_limit_exhausted_is_503_not_a_fake_answer(
    client: httpx.AsyncClient, stub_llm: StubLLM
) -> None:
    from gateway.errors import RateLimitExhausted

    def boom(_: object) -> str:
        raise RateLimitExhausted("HTTP 429 after 5 attempts")

    stub_llm.reply = boom
    r = await client.post("/v1/query", json={"tenant": "alpha", "question": "How much annual leave?"})
    assert r.status_code == 503
    assert r.json()["error"] == "llm_rate_limited"


async def test_request_validation(client: httpx.AsyncClient) -> None:
    assert (await client.post("/v1/query", json={"tenant": "alpha", "question": ""})).status_code == 422
    assert (
        await client.post("/v1/query", json={"tenant": "alpha", "question": "q", "top_k": 99})
    ).status_code == 422
