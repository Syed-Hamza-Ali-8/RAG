"""POST /v1/auth/token — DEV-ONLY token issuer (CLAUDE.md correction H).

Issues an access token for a seeded user identified by tenant slug + email, with no password. It
exists so demos and evals can act as real seeded users through the real auth path. It is disabled
unless AUTH_DEV_ISSUER_ENABLED=true; a production deployment uses the client's identity provider.
"""

from fastapi import APIRouter, HTTPException, Request

from gateway.errors import AuthenticationFailed
from gateway.models.auth import TokenRequest, TokenResponse
from gateway.security.tokens import issue_token

router = APIRouter(prefix="/v1/auth")


@router.post("/token", response_model=TokenResponse)
async def dev_token(body: TokenRequest, request: Request) -> TokenResponse:
    settings = request.app.state.settings
    if not settings.auth_dev_issuer_enabled:
        raise HTTPException(status_code=404)
    async with request.app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT u.id, u.tenant_id FROM users u JOIN tenants t ON t.id = u.tenant_id "
            "WHERE t.slug = $1 AND u.email = $2",
            body.tenant,
            body.email,
        )
    if row is None:
        # Same response for an unknown tenant and an unknown email: no user enumeration.
        raise AuthenticationFailed("unknown tenant or user")
    token = issue_token(settings, user_id=row["id"], tenant_id=row["tenant_id"])
    return TokenResponse(access_token=token, expires_in=settings.jwt_ttl_minutes * 60)
