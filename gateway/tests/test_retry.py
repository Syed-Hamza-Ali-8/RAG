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

    return await with_retry(
        script,
        max_attempts=attempts,
        base_delay_s=1,
        max_delay_s=30,
        network_max_attempts=8,
        network_base_delay_s=2,
        network_max_delay_s=30,
        sleep=fake_sleep,
    )


def connection_error() -> Exception:
    return openai.APIConnectionError(request=_REQ)


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


async def test_network_blip_rides_out_on_its_own_wider_budget(sleeps: list[float]) -> None:
    # Seven connection failures (more than the 3 provider attempts) and the call still succeeds.
    script = Script(*[connection_error()] * 7, "ok")
    assert await run(script, sleeps) == "ok"
    assert len(sleeps) == 7
    # 2 s doubling to a 30 s cap, jittered x0.5-1.5: well over the ~10 s blip that stopped Phase 3.
    assert sum(sleeps) >= 0.5 * (2 + 4 + 8 + 16 + 30 + 30 + 30)
    assert all(s <= 30 for s in sleeps)


async def test_network_budget_exhausted_raises_unavailable(sleeps: list[float]) -> None:
    script = Script(*[openai.APITimeoutError(request=_REQ)] * 8)
    with pytest.raises(LLMUnavailable, match="APITimeoutError after 8 attempts"):
        await run(script, sleeps)
    assert script.calls == 8


async def test_rate_limits_and_network_failures_do_not_share_a_budget(sleeps: list[float]) -> None:
    # Two 429s (one short of the provider budget of 3) interleaved with connection errors: no failure
    # of one kind counts against the other, so the call succeeds.
    script = Script(
        status_error(openai.RateLimitError, 429),
        connection_error(),
        connection_error(),
        status_error(openai.RateLimitError, 429),
        connection_error(),
        "ok",
    )
    assert await run(script, sleeps) == "ok"
    # A third 429 still exhausts the provider budget, however many network retries remain.
    script = Script(
        *[status_error(openai.RateLimitError, 429), connection_error()] * 2,
        status_error(openai.RateLimitError, 429),
    )
    with pytest.raises(RateLimitExhausted):
        await run(script, sleeps)
