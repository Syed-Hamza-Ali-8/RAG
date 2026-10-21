import pytest
from pydantic import SecretStr

from gateway.config import Settings
from gateway.errors import ConfigError


def test_selected_tier_without_model_id_is_a_config_error(settings: Settings) -> None:
    s = settings.model_copy(update={"llm_large_model_id": ""})
    with pytest.raises(ConfigError, match="LLM_LARGE_MODEL_ID"):
        s.provider("large")


def test_complete_tier_resolves(settings: Settings) -> None:
    s = settings.model_copy(update={"llm_small_api_key": SecretStr("sk-very-secret-value")})
    cfg = s.provider("small")
    assert cfg.model_id == "stub-model"
    assert cfg.api_key.get_secret_value() == "sk-very-secret-value"
    assert "sk-very-secret-value" not in repr(cfg)  # SecretStr is never rendered
