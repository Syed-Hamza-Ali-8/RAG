"""FastAPI app. Startup fails fast on unapplied migrations, dim mismatch or missing LLM config."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gateway.api import auth, query
from gateway.config import Settings, get_settings
from gateway.db import assert_embedding_dim, assert_migrations_applied, create_pool
from gateway.errors import (
    AuthenticationFailed,
    LLMProviderError,
    LLMUnavailable,
    RateLimitExhausted,
    TenantNotFound,
)
from gateway.ingest.embedder import Embedder
from gateway.llm.provider import LLM, OpenAICompatibleLLM

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, llm: LLM | None = None) -> FastAPI:
    """`llm` lets tests inject a stub; production builds the configured tier from .env."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        s = settings or get_settings()
        built_llm = llm or OpenAICompatibleLLM(s, s.llm_tier)
        embedder = await asyncio.to_thread(
            Embedder, s.embedding_model_id, s.embedding_dim, s.embedding_cache_dir, s.embedding_batch_size
        )
        pool = await create_pool(s.database_dsn)
        try:
            async with pool.acquire() as conn:
                await assert_migrations_applied(conn)
                await assert_embedding_dim(conn, embedder.dim, s.embedding_dim)
            app.state.settings = s
            app.state.pool = pool
            app.state.embedder = embedder
            app.state.llm = built_llm
            log.info("gateway ready: tier=%s model=%s", built_llm.tier, built_llm.model_id)
            yield
        finally:
            await pool.close()
            if isinstance(built_llm, OpenAICompatibleLLM):
                await built_llm.aclose()

    app = FastAPI(title="Gateway", version="0.1.0", lifespan=lifespan)
    app.include_router(query.router)
    app.include_router(auth.router)

    @app.exception_handler(AuthenticationFailed)
    async def _unauthenticated(_: Request, exc: AuthenticationFailed) -> JSONResponse:
        # The reason is logged, never returned: callers cannot tell a deleted tenant from a bad token.
        log.info("authentication failed: %s", exc)
        return JSONResponse(
            status_code=401, content={"error": "unauthenticated"}, headers={"WWW-Authenticate": "Bearer"}
        )

    @app.exception_handler(TenantNotFound)
    async def _tenant_not_found(_: Request, exc: TenantNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": "tenant_not_found", "tenant": str(exc)})

    @app.exception_handler(RateLimitExhausted)
    async def _rate_limited(_: Request, exc: RateLimitExhausted) -> JSONResponse:
        log.error("rate limit exhausted: %s", exc.describe())  # full detail stays server-side
        return JSONResponse(status_code=503, content={"error": "llm_rate_limited", "detail": str(exc)})

    @app.exception_handler(LLMProviderError)
    async def _llm_error(_: Request, exc: LLMProviderError) -> JSONResponse:
        log.error("LLM provider error: %s", exc)
        status = 503 if isinstance(exc, LLMUnavailable) else 502
        return JSONResponse(status_code=status, content={"error": "llm_error", "detail": str(exc)})

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
