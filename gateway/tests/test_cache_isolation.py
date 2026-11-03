"""Semantic-cache isolation: every probe in eval/adversarial_cache.jsonl, through POST /v1/query.

Pass criteria C1-C8 are in eval/verify_adversarial_cache.py and were committed before any cache code.
Invariant 11: a failing probe means the code is wrong. Never weaken, skip, delete or xfail one.

The stub model echoes its whole prompt (the question and every source) and cites every source, so:
- a cache entry served to the wrong user carries the populating user's restricted values (forbidden
  strings), and
- an entry served for the other question of a near-miss pair carries that other question's text.

A hit is protected twice: the key (tenant, role signature, content words) and a re-check that every
cached citation is readable by the caller now. The mutation tests remove a key component AND the
re-check, so they prove the key itself carries the probes; a separate test shows the re-check alone
still stops restricted values when the signature is removed.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import httpx
import pytest
from openai.types.chat import ChatCompletionMessageParam
from verify_adversarial_cache import load, questions

import gateway.rag
from gateway.cache import semantic
from gateway.cache.semantic import CacheConfig
from gateway.config import Settings
from gateway.ingest.embedder import Embedder
from gateway.ingest.pipeline import ingest_document
from gateway.ingest.seed import CORPUS_DIR
from gateway.llm.prompts import REFUSAL_MESSAGE
from gateway.main import create_app
from gateway.security.tokens import issue_token
from tests.conftest import StubLLM

PROBES = load()
IDS = [p["id"] for p in PROBES]
# Every point of the Phase 4 threshold sweep.
SWEEP = (0.88, 0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99)
_SOURCE_LABELS = [f"[S{n}]" for n in range(1, 21)]


class EchoLLM(StubLLM):
    """'leak': echo the prompt and cite every source; 'refuse': the refusal text, no citations."""

    def __init__(self) -> None:
        super().__init__()
        self.mode = "leak"
        self.reply = self._reply

    def _reply(self, messages: list[ChatCompletionMessageParam]) -> str:
        if self.mode == "refuse":
            return REFUSAL_MESSAGE
        prompt = str(messages[-1]["content"])
        return prompt + "\n" + " ".join(label for label in _SOURCE_LABELS if f'id="{label[1:-1]}"' in prompt)


@pytest.fixture(scope="module")
async def app_client(
    settings: Settings, embedder: Embedder, corpus: dict[str, UUID], pytestconfig: pytest.Config
) -> AsyncIterator[tuple[Any, httpx.AsyncClient, EchoLLM]]:
    llm = EchoLLM()
    update: dict[str, Any] = {"cache_enabled": True}
    if (threshold := pytestconfig.getoption("--cache-threshold")) is not None:
        update["cache_similarity_threshold"] = threshold
    app = create_app(settings.model_copy(update=update), llm=llm, embedder=embedder)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            yield app, client, llm


@pytest.fixture(autouse=True)
async def clean_cache(
    app_client: tuple[Any, httpx.AsyncClient, EchoLLM], pool: asyncpg.Pool
) -> AsyncIterator[None]:
    app, _, llm = app_client
    default = app.state.cache
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM semantic_cache")
    llm.mode = "leak"
    yield
    app.state.cache = default


def with_threshold(app: Any, threshold: float) -> None:
    c: CacheConfig = app.state.cache
    app.state.cache = CacheConfig(threshold, c.ttl_hours, c.bypass_patterns)


async def _user(conn: asyncpg.Connection, tenant: str, email: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT u.id, u.tenant_id, u.roles, u.clearance FROM users u JOIN tenants t ON t.id = u.tenant_id "
        "WHERE t.slug = $1 AND u.email = $2",
        tenant,
        email,
    )


async def reingest(
    pool: asyncpg.Pool,
    embedder: Embedder,
    settings: Settings,
    tenant: str,
    slug: str,
    replace: tuple[str, str] | None = None,
    tmp: Path | None = None,
) -> None:
    """Re-ingest a corpus document through the production pipeline, optionally with its text changed
    (its ACL is the folder's, unchanged)."""
    import json

    folders = json.loads((CORPUS_DIR / "tenants.json").read_text(encoding="utf-8"))["folders"]
    folder = next(f for f in folders if slug.startswith(f + "-"))
    (path,) = (CORPUS_DIR / tenant / folder).glob(slug[len(folder) + 1 :] + ".*")
    if replace is not None:
        assert tmp is not None
        changed = tmp / path.name
        text = path.read_text(encoding="utf-8")
        assert replace[0] in text, f"{replace[0]!r} not in {path}"
        changed.write_text(text.replace(*replace), encoding="utf-8")
        path = changed
    async with pool.acquire() as conn:
        tenant_id = await conn.fetchval("SELECT id FROM tenants WHERE slug = $1", tenant)
    await ingest_document(
        pool,
        embedder,
        settings,
        tenant_id=tenant_id,
        slug=slug,
        path=path,
        allowed_roles=folders[folder]["allowed_roles"],
        min_clearance=folders[folder]["min_clearance"],
        doc_metadata={"folder": folder},
    )


@asynccontextmanager
async def setup_applied(
    probe: dict[str, Any], pool: asyncpg.Pool, embedder: Embedder, settings: Settings, tmp: Path
) -> AsyncIterator[None]:
    """Apply a probe's setup between its two requests; restore everything afterwards."""
    setup, tenant = probe.get("setup", {}), probe["ask"]["tenant"]
    async with pool.acquire() as conn:
        user = await _user(conn, tenant, probe["ask"]["as_user"])
        saved = []
        if setup.get("revoke_roles"):
            await conn.execute(
                "UPDATE users SET roles = array(SELECT r FROM unnest(roles) r WHERE r <> ALL($2::text[])) "
                "WHERE id = $1",
                user["id"],
                setup["revoke_roles"],
            )
        if t := setup.get("tighten_document"):
            saved = await conn.fetch(
                "SELECT c.id, c.allowed_roles, c.min_clearance FROM chunks c "
                "JOIN documents d ON d.id = c.document_id JOIN tenants te ON te.id = d.tenant_id "
                "WHERE te.slug = $1 AND d.slug = $2",
                tenant,
                t["slug"],
            )
            await conn.execute(
                "UPDATE chunks SET allowed_roles = $2, min_clearance = $3 WHERE id = ANY($1::uuid[])",
                [r["id"] for r in saved],
                t["allowed_roles"],
                t["min_clearance"],
            )
        if slug := setup.get("delete_document"):
            await conn.execute(
                "DELETE FROM documents d USING tenants te "
                "WHERE te.id = d.tenant_id AND te.slug = $1 AND d.slug = $2",
                tenant,
                slug,
            )
    if other := setup.get("ingest_other_tenant"):
        await reingest(pool, embedder, settings, other, "public-faq")
    if changed := setup.get("reingest_changed_text"):
        await reingest(pool, embedder, settings, tenant, changed["slug"], tuple(changed["replace"]), tmp)
    try:
        yield
    finally:
        async with pool.acquire() as conn:
            if user is not None:
                await conn.execute("UPDATE users SET roles = $2 WHERE id = $1", user["id"], user["roles"])
            for r in saved:
                await conn.execute(
                    "UPDATE chunks SET allowed_roles = $2, min_clearance = $3 WHERE id = $1",
                    r["id"],
                    r["allowed_roles"],
                    r["min_clearance"],
                )
        if setup.get("delete_document"):
            await reingest(pool, embedder, settings, tenant, setup["delete_document"])
        if changed:
            await reingest(pool, embedder, settings, tenant, changed["slug"])


async def ask(
    client: httpx.AsyncClient, pool: asyncpg.Pool, settings: Settings, side: dict[str, Any], question: str
) -> dict[str, Any]:
    async with pool.acquire() as conn:
        user = await _user(conn, side["tenant"], side["as_user"])
        assert user is not None, side
        before = await conn.fetchval("SELECT coalesce(max(id), 0) FROM audit_log")
    token = issue_token(settings, user_id=user["id"], tenant_id=user["tenant_id"])
    r = await client.post(
        "/v1/query", json={"question": question}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text
    async with pool.acquire() as conn:
        audit = await conn.fetchrow("SELECT * FROM audit_log WHERE id > $1 ORDER BY id DESC LIMIT 1", before)
        ql = await conn.fetchrow("SELECT * FROM query_log WHERE id = $1", audit["query_log_id"])
        rows = await conn.fetchval(
            "SELECT count(*) FROM semantic_cache c JOIN tenants t ON t.id = c.tenant_id "
            "WHERE t.slug = $1 AND c.query_text = $2",
            side["tenant"],
            question,
        )
    return {"body": r.json(), "audit": audit, "ql": ql, "rows": rows}


async def run_probe(
    probe: dict[str, Any],
    client: httpx.AsyncClient,
    llm: EchoLLM,
    pool: asyncpg.Pool,
    embedder: Embedder,
    settings: Settings,
    tmp: Path,
) -> list[str]:
    """Run one probe; return its criterion failures (empty = pass)."""
    pid, cat, expected = probe["id"], probe["category"], probe["expected"]
    q_pop, q_ask = questions(probe)
    llm.mode = "refuse" if probe.get("llm") == "refuses" else "leak"
    twin = probe.get("setup", {}).get("synthetic_same_signature_user")
    fails: list[str] = []
    first = await ask(client, pool, settings, probe["populate"], q_pop)
    if expected in ("miss", "hit") and cat != "non_cacheable":
        if first["ql"]["outcome"] != "answered" or first["rows"] != 1:
            fails.append(f"{pid}: not live: the populate request stored no entry")
    if probe["forbidden_strings"] and not any(
        s.lower() in first["body"]["answer"].lower() for s in probe["forbidden_strings"]
    ):
        fails.append(f"{pid}: not live: the stored answer holds no forbidden string")
    async with pool.acquire() as conn:
        if twin:
            tid = await conn.fetchval("SELECT id FROM tenants WHERE slug = $1", probe["ask"]["tenant"])
            await conn.execute(
                "INSERT INTO users (tenant_id, email, roles, clearance) VALUES ($1, $2, $3, $4)",
                tid,
                twin["email"],
                twin["roles"],
                twin["clearance"],
            )
    try:
        async with setup_applied(probe, pool, embedder, settings, tmp):
            second = await ask(client, pool, settings, probe["ask"], q_ask)
    finally:
        if twin:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM users WHERE email = $1", twin["email"])
    served = second["audit"]["served_from_cache"]
    answer = second["body"]["answer"]
    leaked = [s for s in probe["forbidden_strings"] if s.lower() in answer.lower()]
    if leaked:
        fails.append(f"{pid} C2: forbidden strings in the answer: {leaked}")
    if expected == "miss" and served:
        fails.append(f"{pid} C1/C3/C4: served from a cache entry it must not see")
    if cat == "near_miss" and q_pop in answer:
        fails.append(f"{pid} C3: served the other question's answer")
    if expected == "hit":
        if not served:
            fails.append(f"{pid} C6: expected a cache hit, got a miss")
        else:
            cited = list(dict.fromkeys(UUID(c["chunk_id"]) for c in second["body"]["citations"]))
            if list(second["audit"]["retrieved_ids"]) != cited or not cited:
                fails.append(f"{pid} C7: audit retrieved_ids are not the cached citations")
            if (second["ql"]["cache_hit"], second["ql"]["route_tier"]) != (True, "cached"):
                fails.append(f"{pid} C7: query_log does not record the hit")
    if expected == "bypass":
        if first["ql"]["cache_hit"] is not None or second["ql"]["cache_hit"] is not None or second["rows"]:
            fails.append(f"{pid} C5: a bypassed question touched the cache")
    if cat == "non_cacheable":
        if first["ql"]["outcome"] != "refused" or first["rows"] != 0:
            fails.append(f"{pid} C8: a refusal was stored")
    return fails


@pytest.fixture
def run(
    app_client: tuple[Any, httpx.AsyncClient, EchoLLM],
    pool: asyncpg.Pool,
    embedder: Embedder,
    settings: Settings,
    tmp_path: Path,
) -> Any:
    _, client, llm = app_client

    async def go(probe: dict[str, Any]) -> list[str]:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM semantic_cache")
        return await run_probe(probe, client, llm, pool, embedder, settings, tmp_path)

    return go


@pytest.mark.parametrize("probe", PROBES, ids=IDS)
async def test_probe(probe: dict[str, Any], run: Any) -> None:
    assert await run(probe) == []


NEAR_MISS = [p for p in PROBES if p["category"] == "near_miss"]


@pytest.mark.parametrize("threshold", SWEEP)
@pytest.mark.parametrize("probe", NEAR_MISS, ids=[p["id"] for p in NEAR_MISS])
async def test_near_miss_holds_at_every_sweep_threshold(
    probe: dict[str, Any], threshold: float, run: Any, app_client: tuple[Any, httpx.AsyncClient, EchoLLM]
) -> None:
    with_threshold(app_client[0], threshold)
    assert await run(probe) == []


# --- The suite has teeth: removing each defence makes its probes fail. -----------------------------


@pytest.fixture
def no_recheck(monkeypatch: pytest.MonkeyPatch) -> None:
    async def all_readable(conn: Any, *, acl_filter: Any, chunk_ids: list[UUID]) -> int:
        return len(chunk_ids)

    monkeypatch.setattr(gateway.rag, "readable_count", all_readable)


ROLE_PROBES = [p for p in PROBES if p["category"] in ("cross_role", "cross_clearance")]
TENANT_PROBES = [p for p in PROBES if p["category"] == "cross_tenant"]


@pytest.mark.parametrize("probe", ROLE_PROBES, ids=[p["id"] for p in ROLE_PROBES])
async def test_without_the_role_signature_cross_role_probes_fail(
    probe: dict[str, Any], run: Any, monkeypatch: pytest.MonkeyPatch, no_recheck: None
) -> None:
    monkeypatch.setattr(semantic, "role_signature", lambda roles, clearance: "same-for-everyone")
    fails = await run(probe)
    assert any("must not see" in f for f in fails), f"{probe['id']} is not live: {fails}"
    if probe["forbidden_strings"]:
        assert any("C2" in f for f in fails), (
            f"{probe['id']}: served, but no restricted value reached the answer"
        )


@pytest.mark.parametrize("probe", TENANT_PROBES, ids=[p["id"] for p in TENANT_PROBES])
async def test_without_the_tenant_scope_cross_tenant_probes_fail(
    probe: dict[str, Any], run: Any, monkeypatch: pytest.MonkeyPatch, no_recheck: None
) -> None:
    monkeypatch.setattr(
        semantic, "_scope_predicate", lambda: "$1::uuid IS NOT NULL AND c.role_signature = $2"
    )
    fails = await run(probe)
    assert any("must not see" in f for f in fails) and any("C2" in f for f in fails), (
        f"{probe['id']}: {fails}"
    )


@pytest.mark.parametrize("probe", NEAR_MISS, ids=[p["id"] for p in NEAR_MISS])
async def test_without_the_word_check_near_miss_probes_fail(
    probe: dict[str, Any],
    run: Any,
    monkeypatch: pytest.MonkeyPatch,
    app_client: tuple[Any, httpx.AsyncClient, EchoLLM],
) -> None:
    # Similarity alone at the bottom of the sweep, the configuration the pre-registered finding rules out.
    monkeypatch.setattr(semantic, "content_key", lambda question: "")
    with_threshold(app_client[0], 0.88)
    fails = await run(probe)
    assert any("C3: served the other question" in f for f in fails), f"{probe['id']} is not live: {fails}"


LEAK_ROLE_PROBES = [p for p in ROLE_PROBES if p["forbidden_strings"]]


@pytest.mark.parametrize("probe", LEAK_ROLE_PROBES, ids=[p["id"] for p in LEAK_ROLE_PROBES])
async def test_the_readability_recheck_alone_stops_restricted_values(
    probe: dict[str, Any], run: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Second layer on its own: with the signature removed from the key, a cached answer citing chunks
    # the caller cannot read is discarded, so no restricted value is served.
    monkeypatch.setattr(semantic, "role_signature", lambda roles, clearance: "same-for-everyone")
    fails = await run(probe)
    assert not any("C2" in f for f in fails), f"{probe['id']}: {fails}"


def test_every_probe_is_covered() -> None:
    assert len(set(IDS)) == len(PROBES) == 28
    assert {p["pair"] for p in NEAR_MISS} == {"nm1", "nm2", "nm3", "nm4", "nm5"}
