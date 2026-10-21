import httpx2
import openai
import pytest

from gateway.errors import LLMProviderError, LLMUnavailable, RateLimitExhausted
from gateway.llm.retry import with_retry

_REQ = httpx2.Request("POST", "http://provider.invalid/v1/chat/completions")


def status_error(
    cls: type[openai.APIStatusError], code: int, headers: dict[str, str] | None = None
) -> Exception:
    return cls("err", response=httpx2.Response(code, request=_REQ, headers=headers), body=None)


class Script:
    def __init__(self, *outcomes: object) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    async def __call__(self) -> object:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def sleeps() -> list[float]:
    return []


async def run(script: Script, sleeps: list[float], attempts: int = 3) -> object:
    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    return await with_retry(script, max_attempts=attempts, base_delay_s=1, max_delay_s=30, sleep=fake_sleep)


async def test_retries_429_then_succeeds(sleeps: list[float]) -> None:
    script = Script(status_error(openai.RateLimitError, 429), "ok")
    assert await run(script, sleeps) == "ok"
    assert script.calls == 2
    assert len(sleeps) == 1


async def test_429_exhausted_raises_typed_error(sleeps: list[float]) -> None:
    script = Script(*[status_error(openai.RateLimitError, 429)] * 3)
    with pytest.raises(RateLimitExhausted):
        await run(script, sleeps)
    assert script.calls == 3
    assert len(sleeps) == 2


async def test_backoff_grows_and_honours_retry_after(sleeps: list[float]) -> None:
    script = Script(
        status_error(openai.RateLimitError, 429),
        status_error(openai.RateLimitError, 429, {"retry-after": "20"}),
        "ok",
    )
    await run(script, sleeps)
    assert 0.5 <= sleeps[0] <= 1.5
    assert sleeps[1] >= 20


async def test_5xx_exhausted_raises_unavailable(sleeps: list[float]) -> None:
    script = Script(*[status_error(openai.InternalServerError, 503)] * 3)
    with pytest.raises(LLMUnavailable):
        await run(script, sleeps)


async def test_non_retryable_error_raises_immediately(sleeps: list[float]) -> None:
    script = Script(status_error(openai.AuthenticationError, 401))
    with pytest.raises(LLMProviderError) as exc_info:
        await run(script, sleeps)
    assert not isinstance(exc_info.value, RateLimitExhausted)
    assert script.calls == 1
    assert sleeps == []
