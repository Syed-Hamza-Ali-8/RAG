import httpx2
import openai
import pytest

from gateway.errors import LLMProviderError, LLMUnavailable, RateLimitExhausted
from gateway.llm.retry import with_retry

_REQ = httpx2.Request("POST", "http://provider.invalid/v1/chat/completions")


def status_error(
    cls: type[openai.APIStatusError],
    code: int,
    headers: dict[str, str] | None = None,
    body: object | None = None,
) -> Exception:
    return cls("err", response=httpx2.Response(code, request=_REQ, headers=headers), body=body)


# Shaped like the SDK builds it: body is the JSON "error" object of the provider's response.
GROQ_TPM_BODY = {
    "message": "Rate limit reached for model `openai/gpt-oss-20b` on tokens per minute (TPM): "
    "Limit 8000, Used 7100, Requested 2300. Please try again in 10.5s.",
    "type": "tokens",
    "code": "rate_limit_exceeded",
}
GROQ_HEADERS = {
    "x-ratelimit-limit-tokens": "8000",
    "x-ratelimit-remaining-tokens": "900",
    "x-ratelimit-reset-tokens": "10.5s",
    "x-ratelimit-limit-requests": "1000",
    "retry-after": "11",
    "x-request-id": "req_abc123",
    "set-cookie": "session=secret",
    "authorization": "Bearer should-never-be-kept",
}


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


async def test_exhausted_429_carries_provider_message_and_rate_limit_headers(sleeps: list[float]) -> None:
    script = Script(*[status_error(openai.RateLimitError, 429, GROQ_HEADERS, GROQ_TPM_BODY)] * 3)
    with pytest.raises(RateLimitExhausted) as exc_info:
        await run(script, sleeps)
    exc = exc_info.value
    assert exc.provider_message == GROQ_TPM_BODY["message"]
    assert exc.provider_code == "rate_limit_exceeded"
    assert exc.request_id == "req_abc123"
    assert exc.rate_limit_headers == {
        "retry-after": "11",
        "x-ratelimit-limit-requests": "1000",
        "x-ratelimit-limit-tokens": "8000",
        "x-ratelimit-remaining-tokens": "900",
        "x-ratelimit-reset-tokens": "10.5s",
    }
    full = exc.describe()
    assert "tokens per minute (TPM)" in full and "x-ratelimit-remaining-tokens=900" in full
    assert "secret" not in full and "Bearer" not in full


async def test_short_message_hides_provider_detail(sleeps: list[float]) -> None:
    # str(exc) is what the API returns to tenants; provider detail stays in server logs.
    script = Script(*[status_error(openai.RateLimitError, 429, GROQ_HEADERS, GROQ_TPM_BODY)] * 3)
    with pytest.raises(RateLimitExhausted) as exc_info:
        await run(script, sleeps)
    assert str(exc_info.value) == "HTTP 429 after 3 attempts"


async def test_non_json_429_body_falls_back_to_sdk_message(sleeps: list[float]) -> None:
    script = Script(*[status_error(openai.RateLimitError, 429, body="plain text error")] * 3)
    with pytest.raises(RateLimitExhausted) as exc_info:
        await run(script, sleeps)
    assert exc_info.value.provider_message == "err"
    assert exc_info.value.rate_limit_headers == {}


async def test_each_429_retry_logs_the_provider_message(
    sleeps: list[float], caplog: pytest.LogCaptureFixture
) -> None:
    script = Script(status_error(openai.RateLimitError, 429, GROQ_HEADERS, GROQ_TPM_BODY), "ok")
    with caplog.at_level("WARNING", logger="gateway.llm.retry"):
        await run(script, sleeps)
    (record,) = caplog.records
    assert "tokens per minute (TPM)" in record.getMessage()
    assert "x-ratelimit-remaining-tokens=900" in record.getMessage()
