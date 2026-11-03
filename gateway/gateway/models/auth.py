from pydantic import BaseModel, ConfigDict, Field


class TokenRequest(BaseModel):
    """DEV ONLY (correction H): identify a seeded user by tenant slug + email; no password."""

    model_config = ConfigDict(extra="forbid")

    tenant: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
