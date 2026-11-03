import pytest

from gateway.config import Settings
from gateway.main import create_app
from tests.conftest import StubLLM


async def test_apps_in_tests_cannot_load_a_private_embedder(settings: Settings) -> None:
    # The conftest guard: an app built without the shared embedder fails at startup, before loading weights.
    app = create_app(settings, llm=StubLLM())
    with pytest.raises(RuntimeError, match="shared embedder"):
        async with app.router.lifespan_context(app):
            pass
