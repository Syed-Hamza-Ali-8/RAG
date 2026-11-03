"""Complexity classifier, routing policy, shadow cost, and routing through POST /v1/query."""

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg
import httpx
import pytest

from gateway.config import Settings
from gateway.ingest.embedder import Embedder
from gateway.main import create_app
from gateway.routing.classifier import WEIGHTS, complexity, features
from gateway.routing.policy import Price, Router, price_for, shadow_cost
from gateway.security.tokens import issue_token
from tests.conftest import StubLLM

HIGH = [0.9, 0.85, 0.8, 0.7, 0.65, 0.6]  # confident, well-separated retrieval


def test_weights_sum_to_one_and_score_stays_in_range() -> None:
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    for q, scores in (
        ("Hi?", HIGH),
        ("x " * 80 + "and what, and how, which, if, more than 2026?", []),
        ("", []),
    ):
        c = complexity(q, scores)
        assert 0.0 <= c.score <= 1.0 and set(c.features) == set(WEIGHTS)
        assert all(0.0 <= v <= 1.0 for v in c.features.values())


def test_multi_question_and_clauses() -> None:
    f = features("What is Acme's 2026 budget for Cobalt Cloud hosting, and how much had been spent?", HIGH)
    assert f["multi_question"] == 1.0 and f["clauses"] > 0
    g = features("Who is Acme's Head of People?", HIGH)
    assert g["multi_question"] == 0.0 and g["clauses"] == 0.0


def test_entities_comparatives_and_temporal_markers() -> None:
    f = features("Is the USD 5,000 limit higher than the London one before March 2026?", HIGH)
    assert f["entities"] == 1.0  # USD, 5,000, London, March, 2026
    assert f["comparative"] == 1.0 and f["temporal"] == 1.0
    g = features("who approves expense claims", HIGH)
    assert (g["entities"], g["comparative"], g["temporal"]) == (0.0, 0.0, 0.0)


def test_retrieval_confidence_features() -> None:
    confident = features("q", HIGH)
    unsure = features("q", [0.55, 0.54, 0.54, 0.53, 0.53, 0.52])
    assert confident["low_confidence"] == pytest.approx(0.1) and confident["flat_scores"] == 0.0
    assert unsure["low_confidence"] == pytest.approx(0.45) and unsure["flat_scores"] == pytest.approx(0.85)
    assert features("q", [])["low_confidence"] == features("q", [])["flat_scores"] == 1.0


def test_a_harder_question_scores_higher() -> None:
    easy = complexity("Who is Acme's Head of People?", HIGH).score
    hard = complexity(
        "If Atlas had been down for 250 minutes in a 31-day month, how much Service Credit in euros would "
        "Halvorsen have been owed, and which tier applies?",
        [0.62, 0.61, 0.6, 0.6, 0.59, 0.59],
    ).score
    assert hard > easy + 0.3


def test_policy_threshold_is_inclusive() -> None:
    r = Router(0.5)
    assert (r.route(0.4999), r.route(0.5), r.route(0.9)) == ("small", "large", "large")
    assert Router(1.01).route(1.0) == "small" and Router(0.0).route(0.0) == "large"


def test_shadow_cost_uses_list_prices_and_never_guesses(settings: Settings) -> None:
    price = Price(Decimal("0.075"), Decimal("0.30"))
    assert shadow_cost(price, 2000, 500) == Decimal("0.000300")  # 2000*0.075e-6 + 500*0.30e-6
    assert shadow_cost(None, 2000, 500) is None
    assert shadow_cost(price, None, 500) is None
    assert price_for(settings, "small") is None  # the test settings configure no prices
    priced = settings.model_copy(
        update={
            "llm_small_price_input_per_m": Decimal("0.075"),
            "llm_small_price_output_per_m": Decimal("0.30"),
        }
    )
    assert price_for(priced, "small") == price and price_for(priced, "large") is None


class LargeStub(StubLLM):
    tier = "large"
    model_id = "stub-large"


@pytest.fixture
async def routed(
    settings: Settings, embedder: Embedder, corpus: dict[str, UUID], request: pytest.FixtureRequest
) -> AsyncIterator[tuple[httpx.AsyncClient, StubLLM, LargeStub]]:
    small, large = StubLLM(), LargeStub()
    s = settings.model_copy(
        update={
            "routing_enabled": request.param is not None,
            "routing_threshold": request.param if request.param is not None else 0.5,
            "llm_small_price_input_per_m": Decimal("0.075"),
            "llm_small_price_output_per_m": Decimal("0.30"),
        }
    )
    app = create_app(s, llm=small, large_llm=large, embedder=embedder)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield c, small, large


async def _ask(client: httpx.AsyncClient, pool: asyncpg.Pool, settings: Settings, q: str) -> tuple[Any, Any]:
    async with pool.acquire() as conn:
        u = await conn.fetchrow(
            "SELECT u.id, u.tenant_id FROM users u JOIN tenants t ON t.id = u.tenant_id "
            "WHERE t.slug = 'acme' AND u.email = 'hr@acme.example'"
        )
    token = issue_token(settings, user_id=u["id"], tenant_id=u["tenant_id"])
    r = await client.post("/v1/query", json={"question": q}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT route_tier, complexity_score, est_cost_usd, model_used FROM query_log "
            "WHERE tenant_id = $1 ORDER BY id DESC LIMIT 1",
            u["tenant_id"],
        )
    return r.json(), row


@pytest.mark.parametrize("routed", [1.01], indirect=True)
async def test_below_threshold_goes_to_the_small_tier(
    routed: Any, pool: asyncpg.Pool, settings: Settings
) -> None:
    client, small, large = routed
    body, row = await _ask(client, pool, settings, "How many days of annual leave do employees get?")
    assert (body["tier"], row["route_tier"], row["model_used"]) == ("small", "small", "stub-model")
    assert len(small.calls) == 1 and not large.calls
    assert 0 <= row["complexity_score"] <= 1
    assert row["est_cost_usd"] == shadow_cost(Price(Decimal("0.075"), Decimal("0.30")), 100, 10)


@pytest.mark.parametrize("routed", [0.0], indirect=True)
async def test_above_threshold_goes_to_the_large_tier_with_unknown_cost(
    routed: Any, pool: asyncpg.Pool, settings: Settings
) -> None:
    client, small, large = routed
    body, row = await _ask(client, pool, settings, "How many days of annual leave do employees get?")
    assert (body["tier"], row["route_tier"], row["model_used"]) == ("large", "large", "stub-large")
    assert len(large.calls) == 1 and not small.calls
    assert row["est_cost_usd"] is None  # no large-tier price configured: unknown, never guessed


@pytest.mark.parametrize("routed", [None], indirect=True)
async def test_routing_off_uses_the_configured_tier(
    routed: Any, pool: asyncpg.Pool, settings: Settings
) -> None:
    client, small, large = routed
    body, row = await _ask(client, pool, settings, "How many days of annual leave do employees get?")
    assert (body["tier"], row["route_tier"], row["complexity_score"]) == ("small", "small", None)
    assert len(small.calls) == 1 and not large.calls
