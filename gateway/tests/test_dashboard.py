"""Dashboard endpoints: shapes, validation and the eval allowlist (isolation: test_dashboard_isolation)."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx
import pytest

from gateway.api.dashboard import _eval_history
from gateway.config import Settings
from gateway.ingest.embedder import Embedder
from gateway.main import create_app
from gateway.security.tokens import issue_token
from tests.conftest import StubLLM


def test_eval_history_serves_allowlisted_aggregates_only(tmp_path: Path) -> None:
    record = {"id": "q1", "question": "SECRET-QUESTION", "answer": "SECRET-ANSWER", "judge_raw": "x"}
    aggregate = {
        "retrieval": {"single_hop": {"recall@6": 0.9, "all_hops@10": 0.9, "mrr": 0.8, "ndcg@10": 0.7}},
        "generation": {
            "faithful": {"rate": 0.98, "n": 10, "count": 9},
            "hallucinated_on_unanswerable": ["q090"],
        },
    }
    for n in (10, 2):  # numeric order, not lexical
        (tmp_path / f"phase-{n}.json").write_text(
            json.dumps({"meta": {"baseline": f"Phase {n}"}, "aggregate": aggregate, "records": [record]})
        )
    out = _eval_history(tmp_path)
    assert [b["baseline"] for b in out] == ["Phase 2", "Phase 10"]
    text = json.dumps(out)
    assert "SECRET" not in text and "q090" not in text and "ndcg" not in text
    assert out[0]["generation"]["faithful"] == 0.98 and out[0]["generation"]["correct_answerable"] is None


@pytest.fixture
async def client(
    settings: Settings, embedder: Embedder, pool: asyncpg.Pool, corpus: dict[str, UUID]
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, llm=StubLLM(), embedder=embedder)
    async with app.router.lifespan_context(app):
        async with pool.acquire() as conn:
            u = await conn.fetchrow(
                "SELECT u.id, u.tenant_id FROM users u JOIN tenants t ON t.id = u.tenant_id "
                "WHERE t.slug = 'acme' AND u.email = 'admin@acme.example'"
            )
        token = issue_token(settings, user_id=u["id"], tenant_id=u["tenant_id"])
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://t",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


async def test_summary_shape_and_window_bounds(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/dashboard/summary?hours=24")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "window_hours",
        "queries",
        "outcomes",
        "cache",
        "cost_usd",
        "latency_ms",
        "routing",
        "hourly",
    }
    assert body["window_hours"] == 24 and body["cost_usd"]["model"].startswith("cache hits x mean")
    assert body["cost_usd"]["costed_queries"] <= body["queries"]
    for bad in (0, 721, "x"):
        assert (await client.get(f"/v1/dashboard/summary?hours={bad}")).status_code == 422


async def test_fragments_are_html_and_limits_are_bounded(client: httpx.AsyncClient) -> None:
    for path in ("/v1/dashboard/feed", "/v1/dashboard/audit", "/v1/dashboard/audit?role=hr"):
        r = await client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert (await client.get("/v1/dashboard/feed?limit=201")).status_code == 422
    assert (await client.get("/v1/dashboard/audit?role=")).status_code == 422


async def test_shell_loads_pinned_cdn_assets_and_no_data(client: httpx.AsyncClient) -> None:
    r = await client.get("/dashboard")
    assert r.status_code == 200
    assert "htmx.org@1.9.12" in r.text and "chart.js@4.4.1" in r.text
    assert "Demo only" in r.text  # correction H: the dev issuer is labelled
