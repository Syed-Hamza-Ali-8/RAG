"""Admin API behaviour for a legitimate admin. The adversarial cases are in test_admin_isolation.py."""

from collections.abc import AsyncIterator
from uuid import UUID

import asyncpg
import httpx
import pytest

from gateway.config import Settings
from gateway.ingest.embedder import Embedder
from gateway.main import create_app
from gateway.security.tokens import issue_token
from tests.conftest import StubLLM


@pytest.fixture(scope="module")
async def tenant(pool: asyncpg.Pool) -> UUID:
    async with pool.acquire() as conn:
        tid: UUID = await conn.fetchval(
            "INSERT INTO tenants (slug, name) VALUES ('adminco', 'AdminCo') "
            "ON CONFLICT (slug) DO UPDATE SET name = 'AdminCo' RETURNING id"
        )
        await conn.execute("DELETE FROM users WHERE tenant_id = $1", tid)
    return tid


async def _make(pool: asyncpg.Pool, tenant: UUID, email: str, roles: list[str], clearance: int) -> UUID:
    async with pool.acquire() as conn:
        uid: UUID = await conn.fetchval(
            "INSERT INTO users (tenant_id, email, roles, clearance) VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (tenant_id, email) DO UPDATE SET roles = $3, clearance = $4 RETURNING id",
            tenant,
            email,
            roles,
            clearance,
        )
    return uid


@pytest.fixture(scope="module")
async def client(settings: Settings, tenant: UUID, embedder: Embedder) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, llm=StubLLM(), embedder=embedder)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield c


@pytest.fixture
async def admin(pool: asyncpg.Pool, settings: Settings, tenant: UUID) -> dict[str, str]:
    uid = await _make(pool, tenant, "boss@adminco.example", ["employee", "admin"], 3)
    return {"Authorization": f"Bearer {issue_token(settings, user_id=uid, tenant_id=tenant)}"}


async def test_user_lifecycle(client: httpx.AsyncClient, admin: dict[str, str]) -> None:
    r = await client.post(
        "/v1/admin/users",
        json={"email": "new@adminco.example", "roles": ["employee"], "clearance": 0},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    dup = await client.post(
        "/v1/admin/users", json={"email": "new@adminco.example", "roles": [], "clearance": 0}, headers=admin
    )
    assert dup.status_code == 409 and dup.json() == {"error": "duplicate_user"}

    r = await client.patch(f"/v1/admin/users/{uid}", json={"roles": ["employee", "hr"]}, headers=admin)
    assert r.status_code == 200 and r.json()["roles"] == ["employee", "hr"] and r.json()["clearance"] == 0
    r = await client.patch(f"/v1/admin/users/{uid}", json={"clearance": 2}, headers=admin)
    assert r.json()["roles"] == ["employee", "hr"] and r.json()["clearance"] == 2  # omitted field kept

    emails = [u["email"] for u in (await client.get("/v1/admin/users", headers=admin)).json()]
    assert emails == ["boss@adminco.example", "new@adminco.example"]
    assert (await client.get(f"/v1/admin/users/{uid}", headers=admin)).json()["clearance"] == 2

    assert (await client.delete(f"/v1/admin/users/{uid}", headers=admin)).status_code == 204
    gone = await client.get(f"/v1/admin/users/{uid}", headers=admin)
    assert gone.status_code == 404 and gone.json() == {"error": "not_found"}
    assert (await client.delete(f"/v1/admin/users/{uid}", headers=admin)).status_code == 404


async def test_tenant_read_and_rename(client: httpx.AsyncClient, admin: dict[str, str]) -> None:
    r = await client.patch("/v1/admin/tenant", json={"name": "AdminCo Ltd"}, headers=admin)
    assert r.status_code == 200 and r.json()["name"] == "AdminCo Ltd" and r.json()["slug"] == "adminco"
    assert (await client.get("/v1/admin/tenant", headers=admin)).json()["name"] == "AdminCo Ltd"
    assert (await client.patch("/v1/admin/tenant", json={"slug": "other"}, headers=admin)).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"email": "x@adminco.example", "roles": ["Admin"], "clearance": 0},  # roles are lowercase identifiers
        {"email": "x@adminco.example", "roles": ["hr", "hr"], "clearance": 0},
        {"email": "x@adminco.example", "roles": [], "clearance": 4},
        {"email": "x@adminco.example", "roles": [], "clearance": -1},
        {"email": "not-an-email", "roles": [], "clearance": 0},
        {"email": "x@adminco.example", "roles": ["hr; DROP TABLE users"], "clearance": 0},
    ],
)
async def test_invalid_user_bodies_are_422(
    client: httpx.AsyncClient, admin: dict[str, str], body: dict[str, object]
) -> None:
    assert (await client.post("/v1/admin/users", json=body, headers=admin)).status_code == 422


async def test_role_change_takes_effect_on_the_users_next_request(
    client: httpx.AsyncClient, admin: dict[str, str], pool: asyncpg.Pool, settings: Settings, tenant: UUID
) -> None:
    # A second admin is demoted; the token issued while it was admin stops working at once.
    deputy = await _make(pool, tenant, "deputy@adminco.example", ["employee", "admin"], 1)
    deputy_headers = {"Authorization": f"Bearer {issue_token(settings, user_id=deputy, tenant_id=tenant)}"}
    assert (await client.get("/v1/admin/users", headers=deputy_headers)).status_code == 200
    r = await client.patch(f"/v1/admin/users/{deputy}", json={"roles": ["employee"]}, headers=admin)
    assert r.status_code == 200
    assert (await client.get("/v1/admin/users", headers=deputy_headers)).status_code == 403
