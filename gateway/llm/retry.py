"""Exponential backoff with jitter. Fails loudly with a typed error.

Two independent policies, each with its own attempt budget:
- provider responses (429 rate limits, 5xx): max_attempts, base_delay_s, max_delay_s;
- network failures (connection errors, timeouts): network_max_attempts, network_base_delay_s,
  network_max_delay_s. Wider, so a blip of tens of seconds does not stop a long eval run.
A failure of one kind never spends the other kind's budget."""

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


def _backoff(failures: int, base_s: float, cap_s: float) -> float:
    """Jittered exponential delay, never above the cap."""
    exponential: float = base_s * 2.0 ** (failures - 1)
    return min(cap_s, min(cap_s, exponential) * (0.5 + random.random()))


async def with_retry[T](
    call: Callable[[], Awaitable[T]],
    *,
    max_attempts: int,
    base_delay_s: float,
    max_delay_s: float,
    network_max_attempts: int,
    network_base_delay_s: float,
    network_max_delay_s: float,
    sleep: Sleep = asyncio.sleep,
) -> T:
    provider_failures = network_failures = 0
    while True:
        try:
            return await call()
        except openai.RateLimitError as exc:
            provider_failures += 1
            if provider_failures == max_attempts:
                raise _rate_limit_exhausted(exc, max_attempts) from exc
            headers = " ".join(f"{k}={v}" for k, v in sorted(_rate_limit_headers(exc).items()))
            reason = f"429: {_provider_message(exc)!r} [{headers}]"
            failures, limit = provider_failures, max_attempts
            backoff = _backoff(provider_failures, base_delay_s, max_delay_s)
            wait = min(max_delay_s, max(backoff, _retry_after_s(exc) or 0.0))
        except openai.InternalServerError as exc:
            provider_failures += 1
            if provider_failures == max_attempts:
                raise LLMUnavailable(f"HTTP {exc.status_code} after {max_attempts} attempts") from exc
            reason, failures, limit = str(exc.status_code), provider_failures, max_attempts
            wait = _backoff(provider_failures, base_delay_s, max_delay_s)
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            network_failures += 1
            if network_failures == network_max_attempts:
                raise LLMUnavailable(f"{type(exc).__name__} after {network_max_attempts} attempts") from exc
            reason, failures, limit = type(exc).__name__, network_failures, network_max_attempts
            wait = _backoff(network_failures, network_base_delay_s, network_max_delay_s)
        except openai.APIStatusError as exc:
            raise LLMProviderError(f"HTTP {exc.status_code}: {exc.message}") from exc
        log.warning("LLM call failed (%s), attempt %d/%d, retrying in %.1fs", reason, failures, limit, wait)
        await sleep(wait)
