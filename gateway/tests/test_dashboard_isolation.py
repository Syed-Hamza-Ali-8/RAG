"""Dashboard isolation: every probe in eval/adversarial_dashboard.jsonl (pre-registered before the dashboard
code).

Invariant 11 applies: a failing probe means the code is wrong. Never weaken, skip, delete or xfail one.
Invariant 18 applies: every probe proves its path is live through its `live_control` (EVAL_RESULTS.md, Phase
6 dashboard design: pass rules). Traffic from eval/dashboard_traffic.jsonl is sent through POST /v1/query
first, for both tenants, answered by a stub that quotes its sources, so the logs hold the restricted values
the dashboard must not show.
"""

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import asyncpg
import httpx
import pytest
from fastapi import Depends
from openai.types.chat import ChatCompletionMessageParam

from gateway.config import Settings
from gateway.deps import AuthContext, get_auth_context, require_admin
from gateway.ingest.embedder import Embedder
from gateway.main import create_app
from gateway.security import acl
from gateway.security.tokens import issue_token
from tests.conftest import StubLLM

EVAL = Path(__file__).resolve().parent.parent / "eval"
PROBES = [
    json.loads(line) for line in (EVAL / "adversarial_dashboard.jsonl").read_text().splitlines() if line
]
TRAFFIC = [json.loads(line) for line in (EVAL / "dashboard_traffic.jsonl").read_text().splitlines() if line]
CROSS = [p for p in PROBES if p["category"] in ("dashboard_cross_tenant", "dashboard_tenant_param")]
_SOURCE = re.compile(r'<source id="(S\d+)"')


class QuotingLLM(StubLLM):
    """Answers by quoting every source it was given and citing all of them: the answer holds whatever reached
    the model, so `answer_raw` carries restricted values for the HR question."""

    def __init__(self) -> None:
        super().__init__()
        self.reply = self._quote

    @staticmethod
    def _quote(messages: list[ChatCompletionMessageParam]) -> str:
        prompt = str(messages[-1]["content"])
        return prompt + "\n" + " ".join(f"[{label}]" for label in _SOURCE.findall(prompt))


async def _user(conn: asyncpg.Connection, who: str) -> asyncpg.Record:
    tenant, email = who.split("/", 1)
    row = await conn.fetchrow(
        "SELECT u.id, u.tenant_id, u.roles FROM users u JOIN tenants t ON t.id = u.tenant_id "
        "WHERE t.slug = $1 AND u.email = $2",
        tenant,
        email,
    )
    assert row is not None, f"seeded user {who} missing"
    return row


@pytest.fixture(scope="module")
async def dash(
    settings: Settings, embedder: Embedder, pool: asyncpg.Pool, corpus: dict[str, UUID]
) -> AsyncIterator[dict[str, Any]]:
    s = settings.model_copy(update={"cache_enabled": False})
    app = create_app(s, llm=QuotingLLM(), embedder=embedder)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
    ):
        async with pool.acquire() as conn:
            tokens = {}
            for t in TRAFFIC:
                u = await _user(conn, f"{t['tenant']}/{t['as_user']}")
                tokens[t["marker"]] = issue_token(s, user_id=u["id"], tenant_id=u["tenant_id"])
        for t in TRAFFIC:
            r = await client.post(
                "/v1/query",
                json={"question": t["question"]},
                headers={"Authorization": f"Bearer {tokens[t['marker']]}"},
            )
            assert r.status_code == 200, f"traffic {t['marker']}: {r.status_code} {r.text}"
        yield {"app": app, "client": client, "settings": s, "corpus": corpus}


async def _get(dash: dict[str, Any], pool: asyncpg.Pool, who: str | None, path: str) -> httpx.Response:
    headers = {}
    if who:
        async with pool.acquire() as conn:
            u = await _user(conn, who)
        headers["Authorization"] = (
            f"Bearer {issue_token(dash['settings'], user_id=u['id'], tenant_id=u['tenant_id'])}"
        )
    path = path.replace("{globex_id}", str(dash["corpus"]["globex"]))
    response: httpx.Response = await dash["client"].get(path, headers=headers)
    return response


async def _check(probe: dict[str, Any], dash: dict[str, Any], pool: asyncpg.Pool) -> list[str]:
    """Every failure of the probe's pass rule, as text; an empty list is a pass."""
    pid, fails = probe["id"], []
    setup = probe.get("setup", {})
    saved_roles = None
    if setup.get("revoke_roles"):
        async with pool.acquire() as conn:
            u = await _user(conn, probe["as"])
        token = issue_token(
            dash["settings"], user_id=u["id"], tenant_id=u["tenant_id"]
        )  # issued before the change
        saved_roles = list(u["roles"])
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET roles = array(SELECT r FROM unnest(roles) r WHERE r <> ALL($2::text[])) "
                "WHERE id = $1",
                u["id"],
                setup["revoke_roles"],
            )
        try:
            r = await dash["client"].get(probe["path"], headers={"Authorization": f"Bearer {token}"})
        finally:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE users SET roles = $2 WHERE id = $1", u["id"], saved_roles)
    else:
        r = await _get(dash, pool, probe["as"], probe["path"])
    if r.status_code != probe["expected_status"]:
        return [f"{pid}: status {r.status_code}, expected {probe['expected_status']}"]
    body = r.text
    fails += [f"{pid}: leaked {s!r}" for s in probe.get("absent_strings", []) if s in body]
    fails += [f"{pid}: missing {s!r}" for s in probe.get("present_strings", []) if s not in body]
    if probe.get("same_as"):
        plain = await _get(dash, pool, probe["as"], probe["same_as"])
        if plain.text != body:
            fails.append(f"{pid}: differs from {probe['same_as']}: the tenant parameter changed the response")
    if probe.get("summary_counts_own_tenant_only"):
        async with pool.acquire() as conn:
            u = await _user(conn, probe["as"])
            own = await conn.fetchval(
                "SELECT count(*) FROM query_log WHERE tenant_id = $1 AND purpose = 'query' "
                "AND ts > now() - interval '168 hours'",
                u["tenant_id"],
            )
        if r.json()["queries"] != own:
            fails.append(f"{pid}: summary counts {r.json()['queries']} queries, the tenant has {own}")
    return fails


async def _live(
    probe: dict[str, Any], dash: dict[str, Any], pool: asyncpg.Pool, mp: pytest.MonkeyPatch
) -> str | None:
    """None when the probe's live control holds, else why the probe would pass vacuously."""
    c, pid = probe.get("live_control"), probe["id"]
    if not c:
        return None
    if "present_strings" in c:
        body = (await _get(dash, pool, c["as"], probe["path"])).text
        missing = [s for s in c["present_strings"] if s not in body]
        return f"{pid}: the owner's view lacks {missing}: absence proves nothing" if missing else None
    if c.get("all_tenants_count_exceeds_own"):
        async with pool.acquire() as conn:
            u = await _user(conn, probe["as"])
            own, total = await conn.fetchrow(
                "SELECT count(*) FILTER (WHERE tenant_id = $1), count(*) FROM query_log "
                "WHERE purpose = 'query' AND ts > now() - interval '168 hours'",
                u["tenant_id"],
            )
        return None if total > own else f"{pid}: no other tenant's rows: a missing scope would not show"
    if "without_admin_check_status_not" in c:

        async def no_check(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> AuthContext:
            return auth

        dash["app"].dependency_overrides[require_admin] = no_check
        try:
            status = (await _get(dash, pool, probe["as"], probe["path"])).status_code
        finally:
            dash["app"].dependency_overrides.pop(require_admin)
        return (
            None if status != c["without_admin_check_status_not"] else f"{pid}: 403 not from the role check"
        )
    if "answer_raw_contains" in c:
        a = c["answer_raw_contains"]
        async with pool.acquire() as conn:
            raw = await conn.fetchval(
                "SELECT q.answer_raw FROM audit_log al JOIN query_log q ON q.id = al.query_log_id "
                "WHERE strpos(al.query_text, $1) > 0 ORDER BY al.id DESC LIMIT 1",
                a["marker"],
            )
        return None if raw and a["string"] in raw else f"{pid}: answer_raw lacks {a['string']!r}"
    if "tenant_only_acl_shows" in c:

        def tenant_only(alias: str, first: int) -> str:
            r, c = first + 1, first + 2
            return f"({alias}.tenant_id = ${first} AND ${r}::text[] IS NOT NULL AND ${c}::int IS NOT NULL)"

        with mp.context() as m:
            m.setattr(acl, "acl_predicate", tenant_only)
            body = (await _get(dash, pool, probe["as"], probe["path"])).text
        return (
            None if c["tenant_only_acl_shows"] in body else f"{pid}: the title is absent even without the ACL"
        )
    if "baseline_contains" in c:
        baselines = [p.read_text() for p in dash["settings"].eval_baselines_dir.glob("phase-*.json")]
        return None if any(c["baseline_contains"] in b for b in baselines) else f"{pid}: no baseline holds it"
    if "audit_query_text_contains" in c:
        async with pool.acquire() as conn:
            n = await conn.fetchval(
                "SELECT count(*) FROM audit_log WHERE query_text = $1 OR strpos(query_text, $1) > 0",
                c["audit_query_text_contains"],
            )
        return None if n else f"{pid}: the raw markup never reached the audit log"
    return f"{pid}: unknown live control {sorted(c)}"


@pytest.mark.parametrize("probe", PROBES, ids=[p["id"] for p in PROBES])
async def test_dashboard_probe(
    probe: dict[str, Any], dash: dict[str, Any], pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    fails = await _check(probe, dash, pool)
    assert not fails, fails
    vacuous = await _live(probe, dash, pool, monkeypatch)
    assert vacuous is None, vacuous


@pytest.mark.parametrize("probe", CROSS, ids=[p["id"] for p in CROSS])
async def test_without_the_tenant_scope_cross_tenant_probes_fail(
    probe: dict[str, Any], dash: dict[str, Any], pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mutation: the dashboard's tenant scope replaced by TRUE. Every cross-tenant probe must then fail, or it
    # cannot detect a missing scope.
    monkeypatch.setattr(acl, "tenant_predicate", lambda alias, param: f"(${param}::uuid IS NOT NULL)")
    assert await _check(probe, dash, pool), f"{probe['id']} is not live: it passes without the tenant scope"


def test_every_probe_is_covered() -> None:
    ids = [p["id"] for p in PROBES]
    assert len(ids) == len(set(ids)) == 32
    known = {
        "dashboard_cross_tenant",
        "dashboard_tenant_param",
        "dashboard_non_admin",
        "dashboard_unauthenticated",
        "dashboard_restricted_content",
        "dashboard_eval",
        "dashboard_stale_admin",
        "dashboard_markup_injection",
    }
    assert {p["category"] for p in PROBES} == known
