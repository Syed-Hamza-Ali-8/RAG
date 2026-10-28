"""OpenAI-SDK clients per tier. The tier is chosen in .env; there is no runtime fallback."""

from dataclasses import dataclass
from typing import Protocol

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from gateway.config import Settings, Tier
from gateway.errors import LLMProviderError, TruncatedCompletion
from gateway.llm.retry import with_retry


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None


class LLM(Protocol):
    tier: Tier
    model_id: str

    async def complete(self, messages: list[ChatCompletionMessageParam]) -> Completion: ...


def get_client(settings: Settings, tier: Tier) -> tuple[AsyncOpenAI, str]:
    """Returns (client, model_id). model_id comes from .env, never hardcoded."""
    cfg = settings.provider(tier)
    client = AsyncOpenAI(
        base_url=cfg.base_url,
        api_key=cfg.api_key.get_secret_value(),
        timeout=settings.llm_timeout_s,
        max_retries=0,  # retries are ours (gateway.llm.retry), so 429s surface as typed errors
    )
    return client, cfg.model_id


class OpenAICompatibleLLM:
    def __init__(self, settings: Settings, tier: Tier) -> None:
        self.tier: Tier = tier
        self._client, self.model_id = get_client(settings, tier)
        self._settings = settings

    async def complete(self, messages: list[ChatCompletionMessageParam]) -> Completion:
        s = self._settings
        response = await with_retry(
            lambda: self._client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                temperature=s.llm_temperature,
                max_completion_tokens=s.llm_max_completion_tokens,
            ),
            max_attempts=s.llm_max_attempts,
            base_delay_s=s.llm_backoff_base_s,
            max_delay_s=s.llm_backoff_max_s,
            network_max_attempts=s.llm_network_max_attempts,
            network_base_delay_s=s.llm_network_backoff_base_s,
            network_max_delay_s=s.llm_network_backoff_max_s,
        )
        if not response.choices:
            raise LLMProviderError(f"{self.model_id} returned no choices")
        choice, usage = response.choices[0], response.usage
        if choice.finish_reason == "length":
            raise TruncatedCompletion(
                response.model or self.model_id,
                usage.prompt_tokens if usage else None,
                usage.completion_tokens if usage else None,
                choice.message.content or "",
            )
        if choice.message.content is None:
            raise LLMProviderError(f"{self.model_id} returned no message content")
        return Completion(
            text=choice.message.content,
            model=response.model or self.model_id,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )

    async def aclose(self) -> None:
        await self._client.close()
