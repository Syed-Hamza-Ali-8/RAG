"""Typed settings. Every value comes from the environment / .env; model IDs are never defaulted."""

from decimal import Decimal
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

    # Auth (Phase 3). Tokens carry only user and tenant ids; roles and clearance are read from the
    # database on every request. The dev issuer (correction H) is off unless explicitly enabled.
    jwt_secret: SecretStr
    jwt_ttl_minutes: int = 60
    auth_dev_issuer_enabled: bool = False

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
    # Network failures (connection errors, timeouts) retry on their own, wider schedule.
    llm_network_max_attempts: int = 8
    llm_network_backoff_base_s: float = 2.0
    llm_network_backoff_max_s: float = 30.0
    llm_max_completion_tokens: int = 1000
    llm_temperature: float = 0.0

    # Eval / benchmark pacing to stay under free-tier rate limits (spec §6.2)
    eval_request_delay_ms: int = 30000
    # LLM-as-judge (eval only). An explicit tier choice, like llm_tier; never switched at runtime.
    eval_judge_tier: Tier = "large"
    eval_judge_max_completion_tokens: int = 1500
    # Provider's per-model daily token cap (Groq free tier: 200,000/day, rolling 24 h). Used by the
    # eval pre-flight check; verify the current value in the provider console.
    llm_daily_token_limit: int = 200000

    # Complexity routing (Phase 4). Off until the Phase 4 gate decides; both tiers must be configured.
    routing_enabled: bool = False
    routing_threshold: float = 0.5
    # Shadow cost: list prices in USD per 1M tokens, per tier (EVAL_RESULTS.md cites the source). Unset → the
    # cost is recorded as unknown (NULL), never guessed.
    llm_small_price_input_per_m: Decimal | None = None
    llm_small_price_output_per_m: Decimal | None = None
    llm_large_price_input_per_m: Decimal | None = None
    llm_large_price_output_per_m: Decimal | None = None
    llm_local_price_input_per_m: Decimal | None = None
    llm_local_price_output_per_m: Decimal | None = None

    # Semantic cache (spec 4.2; EVAL_RESULTS.md Phase 4 finding). A hit needs the same tenant, role
    # signature and content words; the cosine threshold is a second filter below the word check.
    cache_enabled: bool = True
    # Midpoint of the sweep's flat region (0.88-0.97); the word check, not this, keeps near-misses apart.
    cache_similarity_threshold: float = 0.95
    cache_ttl_hours: int = 24
    # Questions matching any pattern (case-insensitive regex) are neither served from nor stored in the cache.
    cache_bypass_patterns: list[str] = [
        r"\btoday\b",
        r"\byesterday\b",
        r"\bnow\b",
        r"\bcurrent(ly)?\b",
        r"\blatest\b",
        r"\bas of\b",
        r"\bto date\b",
        r"\b(this|last|next) (week|month|quarter|year)\b",
        r"\bfor (client|customer)\s+\w",  # a named client, not "for client-requested work"
    ]

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
