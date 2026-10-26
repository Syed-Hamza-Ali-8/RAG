"""Admin-surface isolation: every probe in eval/adversarial_admin.jsonl (pre-registered before the admin API).

Invariant 11 applies: a failing probe means the code is wrong. Never weaken, skip, delete or xfail one.

Each probe is checked for its expected status, then for the absence of side effects (`unchanged`
rows and tenants, `not_created` emails) and of foreign data in the response (`absent_strings`).
Two controls stop a probe passing vacuously:
- a cross-tenant 404 is only meaningful if the target exists: its own tenant's admin must read it;
- a 403 is only meaningful if it comes from the role check: with the check removed, the same request
  must not be 403.
`same_as_missing` probes must return exactly what a random, non-existent id returns.
"""

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from fastapi import Depends

from gateway.config import Settings
from gateway.deps import AuthContext, get_auth_context, require_admin
from gateway.ingest.embedder import Embedder
from gateway.ingest.seed import CORPUS_DIR, upsert_tenant, upsert_user
from gateway.main import create_app
from gateway.security.tokens import issue_token
from tests.conftest import StubLLM

PROBES = [
    json.loads(line)
    for line in (Path(__file__).resolve().parent.parent / "eval" / "adversarial_admin.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]
MANIFEST = json.loads((CORPUS_DIR / "tenants.json").read_text(encoding="utf-8"))
_PLACEHOLDER = re.compile(r"\{(self|user:[^}]+|tenant:[^}]+)\}")


async def _restore_manifest(pool: asyncpg.Pool) -> None:
    """Tenants and users exactly as corpus/tenants.json declares them; planted users removed."""
    async with pool.acquire() as conn:
        for t in MANIFEST["tenants"]:
            tid = await upsert_tenant(conn, t["slug"], t["name"])
            for u in t["users"]:
                await upsert_user(conn, tid, u)
        await conn.execute("DELETE FROM users WHERE email LIKE 'planted%'")


@pytest.fixture(scope="module")
async def client(
    settings: Settings, pool: asyncpg.Pool, embedder: Embedder
) -> AsyncIterator[httpx.AsyncClient]:
    await _restore_manifest(pool)
    app = create_app(settings, llm=StubLLM(), embedder=embedder)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


@pytest.fixture(autouse=True)
async def clean_state(pool: asyncpg.Pool, client: httpx.AsyncClient) -> AsyncIterator[None]:
    await _restore_manifest(pool)
    yield
    client.app.dependency_overrides.clear()  # type: ignore[attr-defined]
    await _restore_manifest(pool)


async def _user_row(conn: asyncpg.Connection, ref: str) -> asyncpg.Record | None:
    slug, email = ref.split("/", 1)
    return await conn.fetchrow(
        "SELECT u.id, u.tenant_id, u.email, u.roles, u.clearance FROM users u "
        "JOIN tenants t ON t.id = u.tenant_id WHERE t.slug = $1 AND u.email = $2",
        slug,
        email,
    )


async def _resolve(conn: asyncpg.Connection, probe: dict[str, Any], value: Any) -> Any:
    """Substitute {self}, {user:tenant/email} and {tenant:slug} with real ids."""
    if isinstance(value, dict):
        return {k: await _resolve(conn, probe, v) for k, v in value.items()}
    if not isinstance(value, str):
        return value
    out = value
    for m in _PLACEHOLDER.finditer(value):
        key = m.group(1)
        if key == "self":
            row = await _user_row(conn, probe["as"])
            new = str(row["id"]) if row else ""
        elif key.startswith("user:"):
            row = await _user_row(conn, key[5:])
            assert row is not None, f"{probe['id']}: target {key} is not seeded"
            new = str(row["id"])
        else:
            new = str(await conn.fetchval("SELECT id FROM tenants WHERE slug = $1", key[7:]))
        out = out.replace(m.group(0), new)
    return out


async def _token(pool: asyncpg.Pool, settings: Settings, ref: str) -> dict[str, str]:
    async with pool.acquire() as conn:
        row = await _user_row(conn, ref)
    assert row is not None, ref
    return {"Authorization": f"Bearer {issue_token(settings, user_id=row['id'], tenant_id=row['tenant_id'])}"}


async def _snapshot(pool: asyncpg.Pool, probe: dict[str, Any]) -> dict[str, Any]:
    async with pool.acquire() as conn:
        users = {ref: await _user_row(conn, ref) for ref in probe.get("unchanged", [])}
        tenants = {
            s: await conn.fetchrow("SELECT id, slug, name FROM tenants WHERE slug = $1", s)
            for s in probe.get("unchanged_tenants", [])
        }
    return {
        "users": {k: dict(v) if v else None for k, v in users.items()},
        "tenants": {k: dict(v) for k, v in tenants.items()},
    }


async def _send(
    client: httpx.AsyncClient, probe: dict[str, Any], path: str, body: Any, headers: dict[str, str]
) -> httpx.Response:
    return await client.request(probe["method"], path, json=body, headers=headers)


@pytest.mark.parametrize("probe", PROBES, ids=[p["id"] for p in PROBES])
async def test_admin_probe(
    probe: dict[str, Any], client: httpx.AsyncClient, pool: asyncpg.Pool, settings: Settings
) -> None:
    pid = probe["id"]
    headers = await _token(pool, settings, probe["as"]) if probe["as"] else {}
    async with pool.acquire() as conn:
        path = await _resolve(conn, probe, probe["path"])
        body = await _resolve(conn, probe, probe["body"])
        setup = probe.get("setup", {})
        actor = await _user_row(conn, probe["as"]) if probe["as"] else None
        if setup.get("revoke_roles"):
            await conn.execute(
                "UPDATE users SET roles = array(SELECT r FROM unnest(roles) r WHERE r <> ALL($2::text[])) "
                "WHERE id = $1",
                actor["id"],  # type: ignore[index]
                setup["revoke_roles"],
            )
        if setup.get("delete_user"):
            await conn.execute("DELETE FROM users WHERE id = $1", actor["id"])  # type: ignore[index]
    before = await _snapshot(pool, probe)

    r = await _send(client, probe, path, body, headers)
    assert r.status_code == probe["expected_status"], f"{pid}: {r.status_code} {r.text}"

    assert await _snapshot(pool, probe) == before, f"{pid}: state changed"
    async with pool.acquire() as conn:
        for email in probe.get("not_created", []):
            assert not await conn.fetchval("SELECT count(*) FROM users WHERE email = $1", email), (
                f"{pid}: {email} was created"
            )
    for s in probe.get("absent_strings", []):
        assert s.lower() not in r.text.lower(), f"{pid}: response contains {s!r}"

    if probe.get("same_as_missing"):
        missing_path = re.sub(r"[0-9a-f-]{36}$", str(uuid4()), path)
        missing = await _send(client, probe, missing_path, body, headers)
        assert (missing.status_code, missing.json()) == (r.status_code, r.json()), (
            f"{pid}: another tenant's id is distinguishable from a missing one"
        )
        # Control: the target is real. Its own tenant's admin can read it.
        target_ref = re.search(r"\{user:([^}]+)\}", probe["path"]).group(1)  # type: ignore[union-attr]
        own_admin = f"{target_ref.split('/')[0]}/admin@{target_ref.split('/')[0]}.example"
        own = await client.get(path, headers=await _token(pool, settings, own_admin))
        assert own.status_code == 200, f"{pid}: control failed, target not readable by its own admin"


NON_ADMIN_403 = [p for p in PROBES if p["expected_status"] == 403 and not p.get("setup")]


@pytest.mark.parametrize("probe", NON_ADMIN_403, ids=[p["id"] for p in NON_ADMIN_403])
async def test_403_comes_from_the_role_check(
    probe: dict[str, Any], client: httpx.AsyncClient, pool: asyncpg.Pool, settings: Settings
) -> None:
    async def no_role_check(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> AuthContext:
        return auth

    client.app.dependency_overrides[require_admin] = no_role_check  # type: ignore[attr-defined]
    async with pool.acquire() as conn:
        path = await _resolve(conn, probe, probe["path"])
        body = await _resolve(conn, probe, probe["body"])
    r = await _send(client, probe, path, body, await _token(pool, settings, probe["as"]))
    assert r.status_code != 403 and r.status_code < 500, (
        f"{probe['id']} is not live: without the admin check it returned {r.status_code}"
    )


def test_probe_ids_are_unique_and_categories_known() -> None:
    assert len({p["id"] for p in PROBES}) == len(PROBES) >= 19
    assert {p["category"] for p in PROBES} == {"admin_non_admin", "admin_cross_tenant", "admin_stale"}


async def test_seeded_admins_exist(pool: asyncpg.Pool, client: httpx.AsyncClient) -> None:
    async with pool.acquire() as conn:
        for slug in ("acme", "globex"):
            row = await _user_row(conn, f"{slug}/admin@{slug}.example")
            assert row is not None and "admin" in row["roles"]
            assert isinstance(row["id"], UUID)
