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
    """The LLM provider kept returning HTTP 429 after all retries."""
