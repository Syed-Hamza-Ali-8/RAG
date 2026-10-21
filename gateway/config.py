"""Typed settings. Every value comes from the environment / .env; model IDs are never defaulted."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from gateway.errors import ConfigError

Tier = Literal["small", "large", "local"]


class ProviderConfig(BaseModel):
    base_url: str
    api_key: SecretStr
    model_id: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Postgres
    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    postgres_host: str
    postgres_host_port: int

    # Embeddings
    embedding_model_id: str
    embedding_dim: int
    embedding_cache_dir: Path
    embedding_batch_size: int = 32

    # Chunking (CLAUDE.md correction I)
    chunk_target_tokens: int = 384
    chunk_max_tokens: int = 450
    chunk_overlap_tokens: int = 64

    # Retrieval
    retrieval_top_k: int = 6

    # LLM. The tier is an explicit choice; there is no runtime fallback between tiers.
    llm_tier: Tier
    llm_small_base_url: str = ""
    llm_small_api_key: SecretStr = SecretStr("")
    llm_small_model_id: str = ""
    llm_large_base_url: str = ""
    llm_large_api_key: SecretStr = SecretStr("")
    llm_large_model_id: str = ""
    llm_local_base_url: str = ""
    llm_local_api_key: SecretStr = SecretStr("")
    llm_local_model_id: str = ""
    llm_timeout_s: float = 60.0
    llm_max_attempts: int = 5
    llm_backoff_base_s: float = 1.0
    llm_backoff_max_s: float = 30.0
    llm_max_completion_tokens: int = 700
    llm_temperature: float = 0.0

    # Eval / benchmark pacing to stay under free-tier rate limits (spec §6.2)
    eval_request_delay_ms: int = 15000

    @property
    def database_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_host_port}/{self.postgres_db}"
        )

    def provider(self, tier: Tier) -> ProviderConfig:
        """Return a fully specified provider config for `tier`, or raise ConfigError."""
        base_url = getattr(self, f"llm_{tier}_base_url")
        api_key: SecretStr = getattr(self, f"llm_{tier}_api_key")
        model_id = getattr(self, f"llm_{tier}_model_id")
        missing = [
            name
            for name, value in (
                (f"LLM_{tier.upper()}_BASE_URL", base_url),
                (f"LLM_{tier.upper()}_API_KEY", api_key.get_secret_value()),
                (f"LLM_{tier.upper()}_MODEL_ID", model_id),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                f"LLM tier '{tier}' is not configured; set {', '.join(missing)} in .env "
                "(model IDs come from scripts/resolve_models.py)"
            )
        return ProviderConfig(base_url=base_url, api_key=api_key, model_id=model_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
