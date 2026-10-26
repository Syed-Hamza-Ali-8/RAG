"""Admin API models. Every request model forbids extra fields: a body can never name a tenant,
a tenant id or a record id, so an admin's reach is fixed by the token (adversarial b012-b015)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

Role = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,39}$")]
Clearance = Annotated[int, Field(ge=0, le=3)]  # 0=public .. 3=restricted (migration 001)


def _unique(roles: list[str]) -> list[str]:
    if len(set(roles)) != len(roles):
        raise ValueError("roles must not repeat")
    return roles


Roles = Annotated[list[Role], Field(max_length=20), AfterValidator(_unique)]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    roles: Roles
    clearance: Clearance


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: Roles | None = None
    clearance: Clearance | None = None


class UserOut(BaseModel):
    id: UUID
    email: str
    roles: list[str]
    clearance: int
    created_at: datetime


class TenantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)


class TenantOut(BaseModel):
    slug: str
    name: str
    created_at: datetime
