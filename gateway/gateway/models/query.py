from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QueryRequest(BaseModel):
    # The tenant comes only from the bearer token. Any extra field, a "tenant" included, is
    # rejected with 422 even when it matches the token's tenant (adversarial a009, a010, a039).
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class Citation(BaseModel):
    label: str
    chunk_id: UUID
    document_id: UUID
    document_slug: str
    document_title: str
    chunk_ordinal: int
    heading_path: str | None


class Timings(BaseModel):
    retrieval_ms: int
    llm_ms: int | None
    total_ms: int


class QueryResponse(BaseModel):
    answer: str
    refused: bool
    citations: list[Citation]
    model: str | None
    tier: str
    prompt_version: str
    timings: Timings
