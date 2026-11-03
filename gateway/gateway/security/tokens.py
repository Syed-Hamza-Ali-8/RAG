"""Access tokens (HS256). A token proves WHO the caller is (user and tenant ids), never WHAT they may
read: roles and clearance are looked up in the database for every request (gateway.deps)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from gateway.config import Settings
from gateway.errors import AuthenticationFailed

ISSUER = "gateway"
_ALGORITHM = "HS256"


def issue_token(settings: Settings, *, user_id: UUID, tenant_id: UUID, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "sub": str(user_id),
        "tid": str(tenant_id),
        "iat": issued,
        "exp": issued + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm=_ALGORITHM)


def verify_token(settings: Settings, token: str) -> tuple[UUID, UUID]:
    """Returns (user_id, tenant_id). Any failure is AuthenticationFailed (HTTP 401)."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[_ALGORITHM],
            issuer=ISSUER,
            options={"require": ["exp", "iat", "iss", "sub", "tid"]},
        )
        return UUID(claims["sub"]), UUID(claims["tid"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise AuthenticationFailed(f"invalid token: {type(exc).__name__}") from exc
