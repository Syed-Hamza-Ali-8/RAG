"""ACL isolation suite: every probe in eval/adversarial_set.jsonl against the real seeded corpus.

Pass criteria P1-P4 are defined in eval/verify_adversarial.py and were fixed before any ACL code.
Invariant 11: a failing test here means the code is wrong. Never weaken, skip, delete or xfail one.

No real LLM is called. Two stubs stand in for it:
- LeakyLLM copies every source it was given into its answer and cites all of them. It is the worst
  possible model (fully injected, fully compliant), so P2 holds only if nothing forbidden ever
  reached the prompt. Whether a real model chooses to refuse is an eval question, not tested here.
- RefusingLLM always answers with the refusal text, for P4: a probe's refusal must be identical to a
  genuinely unanswerable question's refusal, through the same code path (the LLM is called in both).

Each probe asks with top_k = LIVE_K, the depth at which the verifier proved the forbidden chunk would
be retrieved with the filter removed. test_every_probe_leaks_without_the_predicate re-proves that on
every run, so this suite cannot silently pass because the probes went stale.

    uv run pytest -q tests/test_acl_isolation.py                  # must pass
    uv run pytest -q tests/test_acl_isolation.py --acl-disabled   # predicate removed: must fail
"""

import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import httpx
import pytest
from openai.types.chat import ChatCompletionMessageParam

import gateway.retrieval
from gateway.config import Settings
from gateway.ingest.embedder import Embedder
from gateway.llm.prompts import REFUSAL_MESSAGE
from gateway.main import create_app
from gateway.security import acl
from gateway.security.tokens import issue_token
from run_eval import load_golden
from tests.conftest import StubLLM
from verify_adversarial import LIVE_K, load, permitted

PROBES = load()
LEAK_PROBES = [p for p in PROBES if p["expected"] in ("refuse", "no_leak_permitted_citations")]
REJECT_PROBES = [p for p in PROBES if p["expected"] in ("reject_422", "reject_401")]
UNANSWERABLE = [g for g in load_golden() if g["type"] == "unanswerable"]
_SOURCE = re.compile(r'<source id="(S\d+)"')


def _no_acl(alias: str, first_param: int) -> str:
    """Mutant: the whole predicate removed (tenant scoping too). Parameters stay referenced so the
    statement still prepares with the same bind values."""
    t, r, c = first_param, first_param + 1, first_param + 2
    return f"(${t}::uuid IS NOT NULL AND ${r}::text[] IS NOT NULL AND ${c}::int IS NOT NULL)"


def _tenant_only(alias: str, first_param: int) -> str:
    """Mutant: role and clearance filtering removed, tenant scoping kept."""
    t, r, c = first_param, first_param + 1, first_param + 2
    return f"({alias}.tenant_id = ${t} AND ${r}::text[] IS NOT NULL AND ${c}::int IS NOT NULL)"


class LeakyLLM(StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.reply = self._dump

    @staticmethod
    def _dump(messages: list[ChatCompletionMessageParam]) -> str:
        prompt = str(messages[-1]["content"])
        labels = _SOURCE.findall(prompt)
        return prompt + "\n" + " ".join(f"[{label}]" for label in labels)


class RefusingLLM(StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.reply = lambda _: REFUSAL_MESSAGE


@pytest.fixture(autouse=True)
def acl_disabled(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.config.getoption("--acl-disabled"):
        monkeypatch.setattr(acl, "acl_predicate", _no_acl)


@asynccontextmanager
async def _apps(settings: Settings, embedder: Embedder, mode: str) -> AsyncIterator[dict[str, Any]]:
    """Two apps over the same database: one with the leaky model, one with the refusing model."""
    s = settings.model_copy(update={"retrieval_mode": mode})
    leaky, refusing = LeakyLLM(), RefusingLLM()
    leaky_app, refusing_app = (
        create_app(s, llm=leaky, embedder=embedder),
        create_app(s, llm=refusing, embedder=embedder),
    )
    async with (
        leaky_app.router.lifespan_context(leaky_app),
        refusing_app.router.lifespan_context(refusing_app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=leaky_app), base_url="http://t") as lc,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=refusing_app), base_url="http://t") as rc,
    ):
        yield {"leaky": (lc, leaky), "refusing": (rc, refusing)}


@pytest.fixture(scope="module", params=["vector", "hybrid", "hybrid_graph"])
async def apps(
    request: pytest.FixtureRequest, settings: Settings, corpus: dict[str, UUID], embedder: Embedder
) -> AsyncIterator[dict[str, Any]]:
    """P1-P4 and the rejection probes run against every retrieval mode: each path filters ACLs itself."""
    async with _apps(settings, embedder, request.param) as a:
        yield a


@pytest.fixture(scope="module")
async def vector_apps(
    settings: Settings, corpus: dict[str, UUID], embedder: Embedder
) -> AsyncIterator[dict[str, Any]]:
    """The liveness (mutation) test: probe liveness was established for the vector top 10."""
    async with _apps(settings, embedder, "vector") as a:
        yield a


async def _user(conn: asyncpg.Connection, tenant: str, email: str) -> asyncpg.Record:
    row = await conn.fetchrow(
        "SELECT u.id, u.tenant_id, u.roles, u.clearance FROM users u JOIN tenants t ON t.id = u.tenant_id "
        "WHERE t.slug = $1 AND u.email = $2",
        tenant,
        email,
    )
    assert row is not None, f"seeded user {email} missing from {tenant}"
    return row


@asynccontextmanager
async def applied_setup(pool: asyncpg.Pool, probe: dict[str, Any]) -> AsyncIterator[None]:
    """Apply a stale_authorization probe's change in the database, then restore it."""
    setup = probe.get("setup", {})
    async with pool.acquire() as conn:
        user = await _user(conn, probe["tenant"], probe["as_user"])
        saved_chunks = []
        if setup.get("revoke_roles"):
            await conn.execute(
                "UPDATE users SET roles = array(SELECT r FROM unnest(roles) r WHERE r <> ALL($2::text[])) "
                "WHERE id = $1",
                user["id"],
                setup["revoke_roles"],
            )
        if t := setup.get("tighten_document"):
            saved_chunks = await conn.fetch(
                "SELECT c.id, c.allowed_roles, c.min_clearance FROM chunks c "
                "JOIN documents d ON d.id = c.document_id WHERE d.tenant_id = $1 AND d.slug = $2",
                user["tenant_id"],
                t["slug"],
            )
            assert saved_chunks, f"{probe['id']}: document {t['slug']} not seeded"
            await conn.execute(
                "UPDATE chunks SET allowed_roles = $2, min_clearance = $3 WHERE id = ANY($1::uuid[])",
                [r["id"] for r in saved_chunks],
                t["allowed_roles"],
                t["min_clearance"],
            )
    try:
        yield
    finally:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET roles = $2 WHERE id = $1", user["id"], user["roles"])
            for r in saved_chunks:
                await conn.execute(
                    "UPDATE chunks SET allowed_roles = $2, min_clearance = $3 WHERE id = $1",
                    r["id"],
                    r["allowed_roles"],
                    r["min_clearance"],
                )


async def ask_as(
    client: httpx.AsyncClient, pool: asyncpg.Pool, settings: Settings, probe: dict[str, Any], question: str
) -> tuple[httpx.Response, dict[str, Any] | None, asyncpg.Record]:
    """Issue the token BEFORE any setup (a stale probe's token predates the change), apply the setup,
    ask, and return the response, its audit row and the user as the database had it at query time."""
    async with pool.acquire() as conn:
        user = await _user(conn, probe["tenant"], probe["as_user"])
        before = await conn.fetchval("SELECT coalesce(max(id), 0) FROM audit_log")
    token = issue_token(settings, user_id=user["id"], tenant_id=user["tenant_id"])
    body = {"question": question, "top_k": LIVE_K, **probe.get("request_overrides", {})}
    async with applied_setup(pool, probe):
        r = await client.post("/v1/query", json=body, headers={"Authorization": f"Bearer {token}"})
        async with pool.acquire() as conn:
            at_query = await _user(conn, probe["tenant"], probe["as_user"])
            audit = await conn.fetch("SELECT * FROM audit_log WHERE id > $1", before)
            ids = [i for row in audit for i in row["retrieved_ids"]]
            ids += [c["chunk_id"] for c in (r.json().get("citations", []) if r.status_code == 200 else [])]
            acls = await conn.fetch(
                "SELECT c.id, t.slug AS tenant, c.allowed_roles, c.min_clearance FROM chunks c "
                "JOIN tenants t ON t.id = c.tenant_id WHERE c.id = ANY($1::uuid[])",
                ids,
            )
    assert len(audit) <= 1, f"{probe['id']}: more than one audit row for one query"
    row = dict(audit[0]) if audit else None
    if row is not None:
        row["_acl"] = {a["id"]: dict(a) for a in acls}
    return r, row, at_query


def _readable(row: dict[str, Any], chunk_id: UUID, probe: dict[str, Any], user: asyncpg.Record) -> bool:
    return permitted(row["_acl"][chunk_id], probe["tenant"], list(user["roles"]), user["clearance"])


@pytest.mark.parametrize("probe", LEAK_PROBES, ids=[p["id"] for p in LEAK_PROBES])
async def test_probe_does_not_leak(
    probe: dict[str, Any], apps: dict[str, Any], pool: asyncpg.Pool, settings: Settings
) -> None:
    client, llm = apps["leaky"]
    calls = len(llm.calls)
    r, audit, user = await ask_as(client, pool, settings, probe, probe["question"])
    assert r.status_code == 200, r.text
    body = r.json()
    pid = probe["id"]
    assert len(llm.calls) == calls + 1, f"{pid}: the LLM was not called"
    assert audit is not None, f"{pid}: no audit row"

    # P1: every chunk retrieval returned (exactly what reached the LLM) is readable by the user now.
    retrieved = list(audit["retrieved_ids"])
    assert len(retrieved) == len(_SOURCE.findall(str(llm.calls[-1][-1]["content"])))
    unreadable = [str(c) for c in retrieved if not _readable(audit, c, probe, user)]
    assert not unreadable, f"{pid} P1: retrieved chunks the user may not read: {unreadable}"

    # P2: no forbidden string in the answer, every citation readable.
    answer = body["answer"].lower()
    leaked = [s for s in probe["forbidden_strings"] if s.lower() in answer]
    assert not leaked, f"{pid} P2: forbidden strings in the answer: {leaked}"
    bad = [c["chunk_id"] for c in body["citations"] if not _readable(audit, UUID(c["chunk_id"]), probe, user)]
    assert not bad, f"{pid} P2: cites chunks the user may not read: {bad}"

    # P3: the audit row belongs to this user and tenant, with the roles the database held at query time.
    assert (audit["tenant_id"], audit["user_id"]) == (user["tenant_id"], user["id"])
    assert (
        sorted(audit["user_roles"]) == sorted(user["roles"]) and audit["user_clearance"] == user["clearance"]
    )


@pytest.fixture(scope="module")
async def unanswerable_refusal(
    apps: dict[str, Any], pool: asyncpg.Pool, settings: Settings
) -> dict[str, Any]:
    """The reference refusal: a genuinely unanswerable golden question, asked by its own seeded user."""
    client, llm = apps["refusing"]
    g = UNANSWERABLE[0]
    calls = len(llm.calls)
    r, _, _ = await ask_as(
        client, pool, settings, {"id": g["id"], "tenant": g["tenant"], "as_user": g["as_user"]}, g["question"]
    )
    assert r.status_code == 200 and len(llm.calls) == calls + 1
    return {"status": r.status_code, "body": r.json()}


def _shape(body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k != "timings"} | {"timings": sorted(body["timings"])}


@pytest.mark.parametrize("probe", LEAK_PROBES, ids=[p["id"] for p in LEAK_PROBES])
async def test_probe_refusal_is_indistinguishable(
    probe: dict[str, Any],
    apps: dict[str, Any],
    pool: asyncpg.Pool,
    settings: Settings,
    unanswerable_refusal: dict[str, Any],
) -> None:
    # P4: same status, same body apart from timing values, same code path (the LLM was called).
    client, llm = apps["refusing"]
    calls = len(llm.calls)
    r, _, _ = await ask_as(client, pool, settings, probe, probe["question"])
    assert len(llm.calls) == calls + 1, f"{probe['id']} P4: refusal took a different code path (no LLM call)"
    assert r.status_code == unanswerable_refusal["status"]
    assert _shape(r.json()) == _shape(unanswerable_refusal["body"])
    assert r.json()["answer"] == REFUSAL_MESSAGE


@pytest.mark.parametrize("probe", REJECT_PROBES, ids=[p["id"] for p in REJECT_PROBES])
async def test_rejected_requests(
    probe: dict[str, Any], apps: dict[str, Any], pool: asyncpg.Pool, settings: Settings
) -> None:
    client, llm = apps["leaky"]
    calls = len(llm.calls)
    async with pool.acquire() as conn:
        before = await conn.fetchval("SELECT coalesce(max(id), 0) FROM audit_log")
    if probe.get("setup", {}).get("synthetic_tenant"):
        r = await _ask_as_deleted_tenant(client, pool, settings, probe)
    else:
        r, _, _ = await ask_as(client, pool, settings, probe, probe["question"])
    expected = {"reject_422": 422, "reject_401": 401}[probe["expected"]]
    assert r.status_code == expected, f"{probe['id']}: {r.status_code} {r.text}"
    assert "answer" not in r.json() and len(llm.calls) == calls
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM audit_log WHERE id > $1", before) == 0


async def _ask_as_deleted_tenant(
    client: httpx.AsyncClient, pool: asyncpg.Pool, settings: Settings, probe: dict[str, Any]
) -> httpx.Response:
    async with pool.acquire() as conn:
        tid: UUID = await conn.fetchval(
            "INSERT INTO tenants (slug, name) VALUES ($1, 'Defunct Co') RETURNING id", probe["tenant"]
        )
        uid: UUID = await conn.fetchval(
            "INSERT INTO users (tenant_id, email, roles, clearance) VALUES ($1, $2, $3, $4) RETURNING id",
            tid,
            probe["as_user"],
            probe["as_role"],
            probe["as_clearance"],
        )
        token = issue_token(settings, user_id=uid, tenant_id=tid)
        await conn.execute("DELETE FROM tenants WHERE id = $1", tid)
    return await client.post(
        "/v1/query", json={"question": probe["question"]}, headers={"Authorization": f"Bearer {token}"}
    )


# --- The suite has teeth: without the predicate, every leak probe leaks. -----------------------------


def _mutant_for(probe: dict[str, Any]) -> Callable[[str, int], str]:
    # The verifier's liveness rule: cross-tenant targets are live with no filter at all; same-tenant
    # targets are live with the role/clearance filter removed and tenant scoping kept.
    return _no_acl if probe["target_tenant"] != probe["tenant"] else _tenant_only


@pytest.mark.parametrize("probe", LEAK_PROBES, ids=[p["id"] for p in LEAK_PROBES])
async def test_every_probe_leaks_without_the_predicate(
    probe: dict[str, Any],
    vector_apps: dict[str, Any],
    pool: asyncpg.Pool,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acl, "acl_predicate", _mutant_for(probe))
    client, _ = vector_apps["leaky"]
    r, _, _ = await ask_as(client, pool, settings, probe, probe["question"])
    answer = r.json()["answer"].lower()
    assert any(s.lower() in answer for s in probe["forbidden_strings"]), (
        f"{probe['id']} is not live: with the predicate removed its forbidden strings still did not reach "
        "the answer, so this probe cannot detect a missing ACL"
    )


# --- Every query that reads chunks goes through the predicate. ----------------------------------------

_READS_CHUNKS = re.compile(r"\b(FROM|JOIN)\s+chunks\b", re.IGNORECASE)
_GATEWAY = Path(gateway.retrieval.__file__).resolve().parent.parent


def test_only_the_retrieval_package_reads_chunks() -> None:
    readers = sorted(
        str(p.relative_to(_GATEWAY))
        for p in _GATEWAY.rglob("*.py")
        if _READS_CHUNKS.search(p.read_text(encoding="utf-8"))
    )
    assert readers and all(r.startswith("retrieval/") for r in readers), readers


def test_every_retrieval_query_contains_the_predicate(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    import pkgutil

    marker = "/*ACL-PREDICATE*/"
    monkeypatch.setattr(acl, "acl_predicate", lambda alias, first: marker)
    builders = 0
    for info in pkgutil.iter_modules(gateway.retrieval.__path__):
        module = importlib.import_module(f"gateway.retrieval.{info.name}")
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        if not _READS_CHUNKS.search(source):
            continue
        for name in dir(module):
            if name.endswith("_sql") and callable(fn := getattr(module, name)):
                sql = fn()
                if _READS_CHUNKS.search(sql):
                    builders += 1
                    assert marker in sql, (
                        f"gateway.retrieval.{info.name}.{name} reads chunks without the predicate"
                    )
    assert builders >= 2


def test_suite_covers_every_probe() -> None:
    covered = {p["id"] for p in LEAK_PROBES} | {p["id"] for p in REJECT_PROBES}
    assert covered == {p["id"] for p in PROBES} and len(covered) == len(PROBES) >= 30
