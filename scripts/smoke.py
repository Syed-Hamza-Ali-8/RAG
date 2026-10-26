"""End-to-end smoke test against the real stack and the configured LLM tier.

Fails loudly (non-zero exit) on the first broken link: Docker, compose services, schema,
corpus, startup checks, or a real query that must come back cited.
"""

import asyncio
import sys
from pathlib import Path

import httpx

from gateway.config import get_settings
from gateway.db import create_pool
from gateway.deps import auth_for_email
from gateway.errors import GatewayError
from gateway.main import create_app
from gateway.security.tokens import issue_token
from gateway.stack import StackNotReady, check_stack, describe

ROOT = Path(__file__).resolve().parent.parent
SMOKE_TENANT = "acme"
SMOKE_USER = "hr@acme.example"  # a real seeded user; the query goes through the auth path
SMOKE_QUESTION = "How many days of paid annual leave do full-time employees get?"
SMOKE_EXPECT = "22"


def fail(msg: str) -> None:
    print(f"SMOKE FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"ok  {msg}")


def check_docker() -> None:
    try:
        status = check_stack()
    except StackNotReady as exc:
        fail(str(exc))
    ok("docker ps; compose services " + ", ".join(status.services) + " healthy")
    if status.other_containers:
        print(describe(status).split("\n", 1)[1])


async def check_app() -> None:
    settings = get_settings()
    pool = await create_pool(settings.database_dsn)
    try:
        async with pool.acquire() as conn:
            chunks = await conn.fetchval(
                "SELECT count(*) FROM chunks c JOIN tenants t ON t.id = c.tenant_id WHERE t.slug = $1",
                SMOKE_TENANT,
            )
            max_log_id = await conn.fetchval("SELECT coalesce(max(id), 0) FROM query_log")
            auth = await auth_for_email(conn, SMOKE_TENANT, SMOKE_USER)
    finally:
        await pool.close()
    if not chunks:
        fail(f"tenant {SMOKE_TENANT!r} has no chunks; run scripts/seed_corpus.py")
    ok(f"tenant {SMOKE_TENANT} has {chunks} chunks")

    app = create_app(settings)
    async with app.router.lifespan_context(app):  # runs startup checks: migrations, dims, LLM config
        ok(f"app startup checks passed (tier={settings.llm_tier})")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://smoke", timeout=120) as client:
            token = issue_token(settings, user_id=auth.user_id, tenant_id=auth.tenant_id)
            r = await client.post(
                "/v1/query", json={"question": SMOKE_QUESTION}, headers={"Authorization": f"Bearer {token}"}
            )
    if r.status_code != 200:
        fail(f"POST /v1/query -> {r.status_code}: {r.text}")
    body = r.json()
    if body["refused"] or not body["citations"]:
        fail(f"answer was refused or uncited: {body['answer']!r}")
    c = body["citations"][0]
    if not c["document_title"] or c["chunk_ordinal"] is None:
        fail(f"citation lacks title/ordinal: {c}")
    if SMOKE_EXPECT not in body["answer"]:
        fail(f"expected {SMOKE_EXPECT!r} in answer, got {body['answer']!r}")
    ok(f"query answered by {body['model']} in {body['timings']['total_ms']} ms")
    print(f"    answer: {body['answer']}")
    print(f"    cites : {c['document_title']} #{c['chunk_ordinal']} ({c['heading_path']})")

    pool = await create_pool(settings.database_dsn)
    try:
        async with pool.acquire() as conn:
            logged = await conn.fetchval("SELECT count(*) FROM query_log WHERE id > $1", max_log_id)
    finally:
        await pool.close()
    if logged != 1:
        fail(f"expected 1 new query_log row, found {logged}")
    ok("query_log row written")
    pool = await create_pool(settings.database_dsn)
    try:
        async with pool.acquire() as conn:
            audited = await conn.fetchval(
                "SELECT count(*) FROM audit_log WHERE query_log_id > $1 AND user_id = $2",
                max_log_id,
                auth.user_id,
            )
    finally:
        await pool.close()
    if audited != 1:
        fail(f"expected 1 new audit_log row for {SMOKE_USER}, found {audited}")
    ok("audit_log row written")


def main() -> None:
    check_docker()
    try:
        asyncio.run(check_app())
    except (GatewayError, OSError) as exc:  # OSError: Postgres unreachable
        fail(f"{type(exc).__name__}: {exc}")
    print("SMOKE PASS")


if __name__ == "__main__":
    main()
