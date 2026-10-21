from uuid import UUID

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    # Phase 1 has no auth, so the tenant is named in the request. Phase 3 replaces this
    # field with the tenant from the JWT AuthContext.
    tenant: str = Field(min_length=1, max_length=100)
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
