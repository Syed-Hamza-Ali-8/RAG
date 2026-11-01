"""OpenAICompatibleLLM over a fake SDK client: finish reasons and content handling."""

from types import SimpleNamespace
from typing import Any

import pytest

from gateway.config import Settings
from gateway.errors import LLMProviderError, TruncatedCompletion
from gateway.llm.provider import OpenAICompatibleLLM


def llm_returning(settings: Settings, **choice: Any) -> OpenAICompatibleLLM:
    response = SimpleNamespace(
        model="stub-model",
        usage=SimpleNamespace(prompt_tokens=2300, completion_tokens=1000),
        choices=[
            SimpleNamespace(
                finish_reason=choice["finish_reason"], message=SimpleNamespace(content=choice["content"])
            )
        ]
        if choice
        else [],
    )

    async def create(**kwargs: Any) -> SimpleNamespace:
        sent.update(kwargs)
        return response

    sent: dict[str, Any] = {}
    llm = OpenAICompatibleLLM(settings, "small")
    llm.sent = sent  # type: ignore[attr-defined]
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))  # type: ignore[assignment]
    return llm


async def test_finish_reason_length_raises_truncated_completion(settings: Settings) -> None:
    for content in ("", None, "half an answer"):
        with pytest.raises(TruncatedCompletion) as exc:
            await llm_returning(settings, finish_reason="length", content=content).complete([])
        assert (exc.value.completion_tokens, exc.value.text) == (1000, content or "")


async def test_complete_answer_is_returned(settings: Settings) -> None:
    out = await llm_returning(settings, finish_reason="stop", content="21 days [S1].").complete([])
    assert (out.text, out.model, out.completion_tokens) == ("21 days [S1].", "stub-model", 1000)


async def test_missing_content_or_choices_is_a_provider_error(settings: Settings) -> None:
    with pytest.raises(LLMProviderError):
        await llm_returning(settings, finish_reason="stop", content=None).complete([])
    with pytest.raises(LLMProviderError):
        await llm_returning(settings).complete([])


async def test_reasoning_effort_is_sent_only_when_set(settings: Settings) -> None:
    default = llm_returning(settings, finish_reason="stop", content="ok")
    await default.complete([])
    assert "reasoning_effort" not in default.sent  # type: ignore[attr-defined]
    low = llm_returning(
        settings.model_copy(update={"llm_reasoning_effort": "low"}), finish_reason="stop", content="ok"
    )
    await low.complete([])
    assert low.sent["reasoning_effort"] == "low"  # type: ignore[attr-defined]
