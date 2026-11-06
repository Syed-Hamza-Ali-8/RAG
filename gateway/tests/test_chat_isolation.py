"""Chat page isolation: every probe in eval/adversarial_chat.jsonl (pre-registered before the chat code).

Invariant 11 applies: a failing probe means the code is wrong. Never weaken, skip, delete or xfail one.
Invariant 18 applies: each probe proves its check is live through its `live_control`. Requests are exactly
the ones the page sends: a token from the demo issuer, then `POST /v1/query` with `{"question": ...}`. The
page's own JavaScript is not executed here (EVAL_RESULTS.md, Phase 6 scope added: not covered by the suite);
its text-only rendering is checked structurally on the served page.
"""

import json
import re
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import httpx
import pytest
from openai.types.chat import ChatCompletionMessageParam

from gateway.config import Settings
from gateway.ingest.embedder import Embedder
from gateway.llm.prompts import REFUSAL_MESSAGE
from gateway.main import create_app
from gateway.models.query import Citation
from gateway.security import acl
from run_eval import load_golden
from tests.conftest import StubLLM
from verify_adversarial import permitted

EVAL = Path(__file__).resolve().parent.parent / "eval"
PROBES = [json.loads(line) for line in (EVAL / "adversarial_chat.jsonl").read_text().splitlines() if line]
BY_ID = {p["id"]: p for p in PROBES}
UNANSWERABLE = next(g for g in load_golden() if g["type"] == "unanswerable" and g["tenant"] == "acme")
_SOURCE = re.compile(r'<source id="(S\d+)"')


def _labels(messages: list[ChatCompletionMessageParam]) -> list[str]:
    return _SOURCE.findall(str(messages[-1]["content"]))


class QuotingLLM(StubLLM):
    """The worst-case model: quotes every source it was given and cites them all."""

    def __init__(self) -> None:
        super().__init__()
        self.reply = lambda m: str(m[-1]["content"]) + "\n" + " ".join(f"[{x}]" for x in _labels(m))


class CitingAllLLM(StubLLM):
    """Cites every source without quoting any: the answer holds no chunk text of its own."""

    def __init__(self) -> None:
        super().__init__()
        self.reply = lambda m: "Answer. " + " ".join(f"[{x}]" for x in _labels(m))


class RefusingLLM(StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.reply = lambda _: REFUSAL_MESSAGE


@pytest.fixture(scope="module")
async def clients(
    settings: Settings, embedder: Embedder, corpus: dict[str, UUID]
) -> AsyncIterator[dict[str, httpx.AsyncClient]]:
    s = settings.model_copy(update={"cache_enabled": False})
    apps = {
        "quoting": create_app(s, llm=QuotingLLM(), embedder=embedder),
        "citing": create_app(s, llm=CitingAllLLM(), embedder=embedder),
        "refusing": create_app(s, llm=RefusingLLM(), embedder=embedder),
    }
    async with AsyncExitStack() as stack:
        out: dict[str, httpx.AsyncClient] = {}
        for name, app in apps.items():
            await stack.enter_async_context(app.router.lifespan_context(app))
            out[name] = await stack.enter_async_context(
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
            )
        yield out


async def _ask(client: httpx.AsyncClient, who: str, question: str) -> httpx.Response:
    """Exactly what the page sends: sign in through the demo issuer, then the question alone."""
    tenant, email = who.split("/", 1)
    t = await client.post("/v1/auth/token", json={"tenant": tenant, "email": email})
    assert t.status_code == 200, f"sign-in as {who}: {t.status_code}"
    token = t.json()["access_token"]
    response: httpx.Response = await client.post(
        "/v1/query", json={"question": question}, headers={"Authorization": f"Bearer {token}"}
    )
    return response


async def _page(clients: dict[str, httpx.AsyncClient]) -> str:
    r = await clients["quoting"].get("/chat")
    assert r.status_code == 200
    return r.text


def _script(page: str) -> str:
    return "\n".join(re.findall(r"<script>(.*?)</script>", page, re.S))


# Structural checkers: each returns the violations in a page; the live controls run them on a mutant.
def _forbidden_tokens(page: str, probe: dict[str, Any]) -> list[str]:
    script = _script(page)
    return [t for t in probe["forbidden_tokens"] if t in script or (t.startswith("hx-") and t in page)]


def _fields(page: str, probe: dict[str, Any]) -> list[str]:
    script = _script(page)
    bad = {f for f in re.findall(r"\br\.(\w+)", script) if f not in probe["allowed_response_fields"]}
    bad |= {f for f in re.findall(r"\bc\.(\w+)", script) if f not in probe["allowed_citation_fields"]}
    return sorted(bad)


def _phrases(page: str, probe: dict[str, Any]) -> list[str]:
    low = page.lower()
    return [p for p in probe["forbidden_phrases"] if p in low]


def _fetch_targets(page: str, probe: dict[str, Any]) -> list[str]:
    targets = re.findall(r"fetch\(\s*[\"'`]([^\"'`]+)[\"'`]", _script(page))
    return [t for t in targets if t not in probe["allowed_targets"]] + ([] if targets else ["no fetch found"])


CHECKERS = {
    "page_script": _forbidden_tokens,
    "page_fields": _fields,
    "page_text": _phrases,
    "page_fetch_targets": _fetch_targets,
}


def _mutant(page: str, line: str) -> str:
    return page.replace("</script>", line + "\n</script>", 1)


async def _unreadable(pool: asyncpg.Pool, who: str, response: httpx.Response) -> list[str]:
    """P1: every chunk the response cites, and every chunk the audit log says reached the model for this
    query, must be readable by the asker as the database holds their roles now. Returns the violations."""
    tenant, email = who.split("/", 1)
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT u.id, u.roles, u.clearance FROM users u JOIN tenants t ON t.id = u.tenant_id "
            "WHERE t.slug = $1 AND u.email = $2",
            tenant,
            email,
        )
        retrieved = await conn.fetchval(
            "SELECT retrieved_ids FROM audit_log WHERE user_id = $1 ORDER BY id DESC LIMIT 1", user["id"]
        )
        ids = {UUID(c["chunk_id"]) for c in response.json()["citations"]} | set(retrieved or [])
        rows = await conn.fetch(
            "SELECT c.id, t.slug AS tenant, c.allowed_roles, c.min_clearance, d.slug AS doc, c.ordinal "
            "FROM chunks c JOIN tenants t ON t.id = c.tenant_id JOIN documents d ON d.id = c.document_id "
            "WHERE c.id = ANY($1::uuid[])",
            list(ids),
        )
    return [
        f"{r['tenant']}/{r['doc']}#{r['ordinal']}"
        for r in rows
        if not permitted(dict(r), tenant, list(user["roles"]), user["clearance"])
    ]


def _tenant_only(alias: str, first: int) -> str:
    r, c = first + 1, first + 2
    return f"({alias}.tenant_id = ${first} AND ${r}::text[] IS NOT NULL AND ${c}::int IS NOT NULL)"


def _no_acl(alias: str, first: int) -> str:
    r, c = first + 1, first + 2
    return f"(${first}::uuid IS NOT NULL AND ${r}::text[] IS NOT NULL AND ${c}::int IS NOT NULL)"


@pytest.mark.parametrize("pid", ["c001", "c002"])
async def test_a_user_sees_only_what_their_role_permits(
    pid: str, clients: dict[str, httpx.AsyncClient], pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = BY_ID[pid]
    r = await _ask(clients["quoting"], probe["as_user"], probe["question"])
    assert r.status_code == 200, r.text
    leaked = [s for s in probe["forbidden_strings"] if s in r.text]
    assert not leaked, f"{pid}: leaked {leaked}"
    c = probe["live_control"]
    owner = await _ask(clients["quoting"], c["as_user"], probe["question"])
    missing = [s for s in c["present_strings"] if s not in owner.text]
    assert not missing, f"{pid} is not live: the permitted user does not get {missing}"
    # P1, the property itself rather than chosen strings.
    assert probe["p1_cited_readable"]
    unreadable = await _unreadable(pool, probe["as_user"], r)
    assert not unreadable, f"{pid} P1: cited or retrieved chunks the asker may not read: {unreadable}"
    mutant = _no_acl if "no_acl_cites_unreadable" in probe["p1_live_control"] else _tenant_only
    with monkeypatch.context() as m:
        m.setattr(acl, "acl_predicate", mutant)
        mutated = await _ask(clients["quoting"], probe["as_user"], probe["question"])
    assert await _unreadable(pool, probe["as_user"], mutated), (
        f"{pid} P1 is not live: with the ACL mutated, the response still cites only readable chunks"
    )


async def test_c003_refusal_is_indistinguishable_from_an_unanswerable_question(
    clients: dict[str, httpx.AsyncClient],
) -> None:
    probe = BY_ID["c003"]
    acl = (await _ask(clients["refusing"], probe["as_user"], probe["question"])).json()
    none = (await _ask(clients["refusing"], probe["as_user"], UNANSWERABLE["question"])).json()
    keys = ("answer", "refused", "citations", "model", "tier", "prompt_version")
    assert {k: acl[k] for k in keys} == {k: none[k] for k in keys}
    assert set(acl) == set(none)  # no field present only for one kind of refusal
    owner = (await _ask(clients["quoting"], probe["live_control"]["as_user"], probe["question"])).json()
    assert owner["refused"] is probe["live_control"]["refused"], (
        "c003 is not live: the permitted user is refused too"
    )


async def test_c004_the_response_carries_no_chunk_text(
    clients: dict[str, httpx.AsyncClient], pool: asyncpg.Pool
) -> None:
    probe = BY_ID["c004"]
    r = await _ask(clients["citing"], probe["as_user"], probe["question"])
    assert r.status_code == 200 and not r.json()["refused"], r.text
    leaked = [s for s in probe["absent_strings"] if s in r.text]
    assert not leaked, f"c004: chunk text in the response: {leaked}"
    cited = [UUID(c["chunk_id"]) for c in r.json()["citations"]]
    async with pool.acquire() as conn:
        contents = [
            x["content"] for x in await conn.fetch("SELECT content FROM chunks WHERE id = ANY($1)", cited)
        ]
    target = probe["live_control"]["cited_chunk_contains"]
    assert any(target in t for t in contents), "c004 is not live: no cited chunk holds the sentence"


def test_c005_citations_have_no_content_field() -> None:
    assert sorted(Citation.model_fields) == sorted(BY_ID["c005"]["allowed_fields"])


@pytest.mark.parametrize("pid", ["c006", "c007", "c008", "c009"])
async def test_structural_page_checks_and_their_live_controls(
    pid: str, clients: dict[str, httpx.AsyncClient]
) -> None:
    probe = BY_ID[pid]
    page = await _page(clients)
    check = CHECKERS[probe["structural"]]
    assert check(page, probe) == [], f"{pid}: {check(page, probe)}"
    mutant = _mutant(page, probe["live_control"]["checker_flags_mutant"])
    assert check(mutant, probe), f"{pid} is not live: its checker does not flag the mutant"


async def test_c010_the_page_holds_no_data(clients: dict[str, httpx.AsyncClient], pool: asyncpg.Pool) -> None:
    probe = BY_ID["c010"]
    r = await clients["quoting"].get(probe["path"])  # no token
    assert r.status_code == probe["expected_status"]
    assert [s for s in probe["absent_strings"] if s in r.text] == []
    async with pool.acquire() as conn:
        n = await conn.fetchval(
            "SELECT count(*) FROM chunks WHERE strpos(content, $1) > 0", probe["live_control"]["db_contains"]
        )
    assert n, "c010 is not live: the corpus does not hold the sentence"


async def test_c011_a_question_carrying_markup_comes_back_as_json(
    clients: dict[str, httpx.AsyncClient],
) -> None:
    probe = BY_ID["c011"]
    r = await _ask(clients["citing"], probe["as_user"], probe["question"])
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(probe["expected_content_type"])


def test_every_probe_is_exercised() -> None:
    assert sorted(BY_ID) == [f"c{n:03d}" for n in range(1, 12)]
