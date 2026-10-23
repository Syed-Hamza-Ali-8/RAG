"""Exponential backoff with jitter on 429 / 5xx / timeouts. Fails loudly with a typed error."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

import openai

from gateway.errors import LLMProviderError, LLMUnavailable, RateLimitExhausted

log = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]


def _retry_after_s(exc: openai.APIStatusError) -> float | None:
    value = exc.response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _rate_limit_headers(exc: openai.APIStatusError) -> dict[str, str]:
    """Only rate-limit headers; never authorization, cookies or anything else."""
    return {
        k.lower(): v
        for k, v in exc.response.headers.items()
        if k.lower().startswith("x-ratelimit-") or k.lower() == "retry-after"
    }


def _provider_message(exc: openai.APIStatusError) -> str:
    # The SDK sets exc.body to the JSON "error" object when the response body is JSON.
    message = exc.body.get("message") if isinstance(exc.body, dict) else None
    return message if isinstance(message, str) else exc.message


def _rate_limit_exhausted(exc: openai.RateLimitError, attempts: int) -> RateLimitExhausted:
    return RateLimitExhausted(
        f"HTTP 429 after {attempts} attempts",
        provider_message=_provider_message(exc),
        provider_code=exc.code,
        request_id=exc.request_id,
        rate_limit_headers=_rate_limit_headers(exc),
    )


async def with_retry[T](
    call: Callable[[], Awaitable[T]],
    *,
    max_attempts: int,
    base_delay_s: float,
    max_delay_s: float,
    sleep: Sleep = asyncio.sleep,
) -> T:
    for attempt in range(1, max_attempts + 1):
        try:
            return await call()
        except openai.RateLimitError as exc:
            if attempt == max_attempts:
                raise _rate_limit_exhausted(exc, max_attempts) from exc
            delay = _retry_after_s(exc)
            headers = " ".join(f"{k}={v}" for k, v in sorted(_rate_limit_headers(exc).items()))
            reason = f"429: {_provider_message(exc)!r} [{headers}]"
        except openai.InternalServerError as exc:
            if attempt == max_attempts:
                raise LLMUnavailable(f"HTTP {exc.status_code} after {max_attempts} attempts") from exc
            delay, reason = None, str(exc.status_code)
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            if attempt == max_attempts:
                raise LLMUnavailable(f"{type(exc).__name__} after {max_attempts} attempts") from exc
            delay, reason = None, type(exc).__name__
        except openai.APIStatusError as exc:
            raise LLMProviderError(f"HTTP {exc.status_code}: {exc.message}") from exc
        backoff = min(max_delay_s, base_delay_s * 2 ** (attempt - 1)) * (0.5 + random.random())
        wait = min(max_delay_s, max(backoff, delay or 0.0))
        log.warning(
            "LLM call failed (%s), attempt %d/%d, retrying in %.1fs", reason, attempt, max_attempts, wait
        )
        await sleep(wait)
    raise AssertionError("unreachable")
