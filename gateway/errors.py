"""Typed exceptions. Every failure path raises one of these; nothing degrades silently."""


class GatewayError(Exception):
    """Base for all Gateway errors."""


class ConfigError(GatewayError):
    """Required configuration is missing or inconsistent."""


class EmbeddingModelError(GatewayError):
    """The embedding model failed to load or to embed."""


class EmbeddingDimensionMismatch(GatewayError):
    """Model output dim, EMBEDDING_DIM and the chunks.embedding column disagree."""


class ChunkTooLarge(GatewayError):
    """A chunk exceeds the chunk hard max or the embedding model's max sequence length."""


class UnsupportedDocumentType(GatewayError):
    """No loader exists for this file type."""


class DocumentLoadError(GatewayError):
    """A loader could not extract text from a document."""


class MigrationsNotApplied(GatewayError):
    """The database schema is behind the migrations directory."""


class TenantNotFound(GatewayError):
    """No tenant with the given slug."""


class LLMProviderError(GatewayError):
    """The LLM provider returned a non-retryable error."""


class LLMUnavailable(LLMProviderError):
    """The LLM provider kept failing (5xx / timeout / connection) after all retries."""


class RateLimitExhausted(LLMProviderError):
    """The LLM provider kept returning HTTP 429 after all retries.

    str(exc) is the short summary returned to API callers. The provider's own message, error
    code, request id and rate-limit headers from the last 429 are kept for server-side
    diagnosis; describe() renders all of it for logs. No other headers are kept."""

    def __init__(
        self,
        message: str,
        *,
        provider_message: str | None = None,
        provider_code: str | None = None,
        request_id: str | None = None,
        rate_limit_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_message = provider_message
        self.provider_code = provider_code
        self.request_id = request_id
        self.rate_limit_headers = rate_limit_headers or {}

    def describe(self) -> str:
        headers = " ".join(f"{k}={v}" for k, v in sorted(self.rate_limit_headers.items()))
        return (
            f"{self} | provider_code={self.provider_code} request_id={self.request_id} "
            f"| provider_message={self.provider_message!r} | headers: {headers or 'none'}"
        )
