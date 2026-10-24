from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from pydantic import SecretStr

from gateway.config import Settings
from gateway.errors import AuthenticationFailed
from gateway.security.tokens import ISSUER, issue_token, verify_token


def test_round_trip_carries_identity_only(settings: Settings) -> None:
    user, tenant = uuid4(), uuid4()
    token = issue_token(settings, user_id=user, tenant_id=tenant)
    assert verify_token(settings, token) == (user, tenant)
    claims = jwt.decode(token, options={"verify_signature": False})
    # Roles and clearance are never in the token: they are read from the database per request.
    assert set(claims) == {"iss", "sub", "tid", "iat", "exp"}


def test_expired_token_is_rejected(settings: Settings) -> None:
    old = issue_token(settings, user_id=uuid4(), tenant_id=uuid4(), now=datetime.now(UTC) - timedelta(days=1))
    with pytest.raises(AuthenticationFailed, match="ExpiredSignature"):
        verify_token(settings, old)


def test_wrong_secret_is_rejected(settings: Settings) -> None:
    other = settings.model_copy(update={"jwt_secret": SecretStr("a-different-secret-of-at-least-32-bytes")})
    with pytest.raises(AuthenticationFailed):
        verify_token(settings, issue_token(other, user_id=uuid4(), tenant_id=uuid4()))


def _sign(settings: Settings, claims: dict[str, object], algorithm: str = "HS256") -> str:
    return jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm=algorithm)


def _claims(**over: object) -> dict[str, object]:
    now = datetime.now(UTC)
    base: dict[str, object] = {
        "iss": ISSUER,
        "sub": str(uuid4()),
        "tid": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


@pytest.mark.parametrize(
    "claims",
    [
        _claims(tid=None),  # missing tenant
        _claims(sub=None),  # missing subject
        _claims(exp=None),  # no expiry
        _claims(iss="someone-else"),
        _claims(sub="not-a-uuid"),
        _claims(tid="not-a-uuid"),
    ],
)
def test_malformed_claims_are_rejected(settings: Settings, claims: dict[str, object]) -> None:
    with pytest.raises(AuthenticationFailed):
        verify_token(settings, _sign(settings, claims))


def test_unsigned_and_other_algorithms_are_rejected(settings: Settings) -> None:
    with pytest.raises(AuthenticationFailed):
        verify_token(settings, jwt.encode(_claims(), key=None, algorithm="none"))
    with pytest.raises(AuthenticationFailed):
        verify_token(settings, _sign(settings, _claims(), algorithm="HS512"))
