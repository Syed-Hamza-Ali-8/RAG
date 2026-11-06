"""The chat page route: served without a token, as static HTML (isolation: test_chat_isolation)."""

from uuid import UUID

import httpx

from gateway.config import Settings
from gateway.ingest.embedder import Embedder
from gateway.main import create_app
from tests.conftest import StubLLM


async def test_chat_page_is_static_html(
    settings: Settings, embedder: Embedder, corpus: dict[str, UUID]
) -> None:
    app = create_app(settings, llm=StubLLM(), embedder=embedder)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
    ):
        r = await client.get("/chat")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert (
        'fetch("/v1/query"' in r.text and "Demo only" in r.text
    )  # correction H: the demo issuer is labelled
