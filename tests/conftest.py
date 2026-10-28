"""Shared fixtures. DB tests run against TEST_POSTGRES_DB on the compose Postgres, which is
dropped and recreated per session. If Postgres is unreachable the tests fail, not skip."""

import os
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest
from dotenv import dotenv_values
from openai.types.chat import ChatCompletionMessageParam

import gateway.main
from gateway.config import Settings
from gateway.db import apply_migrations, create_pool
from gateway.ingest.embedder import Embedder
from gateway.ingest.seed import seed_corpus
from gateway.llm.provider import Completion

ROOT = Path(__file__).resolve().parent.parent


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--acl-disabled",
        action="store_true",
        help="DEMONSTRATION ONLY: remove the ACL predicate so tests/test_acl_isolation.py visibly fails",
    )
    parser.addoption(
        "--cache-threshold",
        type=float,
        default=None,
        help="run tests/test_cache_isolation.py at this cache similarity threshold (the sweep's hard gate)",
    )


def _test_db_name() -> str:
    name = os.environ.get("TEST_POSTGRES_DB") or dotenv_values(ROOT / ".env").get("TEST_POSTGRES_DB")
    if not name:
        raise RuntimeError("set TEST_POSTGRES_DB in .env")
    if not name.endswith("_test"):
        raise RuntimeError(f"refusing to drop {name!r}: TEST_POSTGRES_DB must end with '_test'")
    return name


def _no_private_embedder(*_: object, **__: object) -> None:
    raise RuntimeError(
        "a test built an app without the shared embedder: pass create_app(..., embedder=embedder). "
        "Each Embedder holds ~130 MB; one per test app peaked at 1.4 GB and crashed WSL runs (CLAUDE.md)."
    )


@pytest.fixture(scope="session", autouse=True)
def one_embedder_per_session() -> Iterator[None]:
    """Standing constraint: tests share the session `embedder`; apps never load their own."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(gateway.main, "Embedder", _no_private_embedder)
        yield


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=ROOT / ".env",
        postgres_db=_test_db_name(),
        llm_tier="small",
        llm_small_base_url="http://stub.invalid/v1",
        llm_small_api_key="stub",
        llm_small_model_id="stub-model",
        cache_enabled=False,  # suites that test the cache turn it on explicitly
    )


@pytest.fixture(scope="session")
async def test_db(settings: Settings) -> AsyncIterator[str]:
    admin_dsn = settings.database_dsn.rsplit("/", 1)[0] + "/postgres"
    admin = await asyncpg.connect(admin_dsn)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{settings.postgres_db}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{settings.postgres_db}"')
    finally:
        await admin.close()
    conn = await asyncpg.connect(settings.database_dsn)
    try:
        await apply_migrations(conn)
    finally:
        await conn.close()
    yield settings.database_dsn


@pytest.fixture(scope="session")
async def pool(test_db: str) -> AsyncIterator[asyncpg.Pool]:
    p = await create_pool(test_db)
    yield p
    await p.close()


@pytest.fixture(scope="session")
def embedder(settings: Settings) -> Embedder:
    return Embedder(
        settings.embedding_model_id,
        settings.embedding_dim,
        settings.embedding_cache_dir,
        settings.embedding_batch_size,
    )


@pytest.fixture(scope="session")
async def corpus(pool: asyncpg.Pool, embedder: Embedder, settings: Settings) -> dict[str, UUID]:
    """The real corpus, tenants and users, seeded once into the test database by the production seeder.
    Shared by the isolation suites; a suite that changes a document restores it before it ends."""
    await seed_corpus(pool, embedder, settings)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT slug, id FROM tenants WHERE slug = ANY($1::text[])", ["acme", "globex"]
        )
    return {r["slug"]: r["id"] for r in rows}


class StubLLM:
    """Records prompts and returns a scripted answer. Never touches the network."""

    tier = "small"
    model_id = "stub-model"

    def __init__(self) -> None:
        self.calls: list[list[ChatCompletionMessageParam]] = []
        self.reply: Callable[[list[ChatCompletionMessageParam]], str] = lambda _: "Answer [S1]."

    async def complete(self, messages: list[ChatCompletionMessageParam]) -> Completion:
        self.calls.append(messages)
        return Completion(self.reply(messages), self.model_id, prompt_tokens=100, completion_tokens=10)


@pytest.fixture
def stub_llm() -> StubLLM:
    return StubLLM()
