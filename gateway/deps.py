"""AuthContext: the caller's identity and permissions, resolved from the database on every request.

Nothing about permissions is taken from the token. A removed role, a lowered clearance, a deleted
user or a deleted tenant takes effect on the very next request (adversarial probes a040-a042).
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gateway.errors import AuthenticationFailed, Forbidden
from gateway.security.acl import AclFilter
from gateway.security.tokens import verify_token

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    tenant_id: UUID
    user_id: UUID
    roles: tuple[str, ...]
    clearance: int

    def acl(self) -> AclFilter:
        return AclFilter(tenant_id=self.tenant_id, roles=self.roles, clearance=self.clearance)


async def load_auth_context(conn: asyncpg.Connection, user_id: UUID, tenant_id: UUID) -> AuthContext:
    row = await conn.fetchrow(
        """
        SELECT u.id, u.tenant_id, u.roles, u.clearance
        FROM users u JOIN tenants t ON t.id = u.tenant_id
        WHERE u.id = $1 AND u.tenant_id = $2
        """,
        user_id,
        tenant_id,
    )
    if row is None:
        raise AuthenticationFailed("user or tenant no longer exists")
    return AuthContext(
        tenant_id=row["tenant_id"], user_id=row["id"], roles=tuple(row["roles"]), clearance=row["clearance"]
    )


async def auth_for_email(conn: asyncpg.Connection, tenant_slug: str, email: str) -> AuthContext:
    """Resolve a seeded user by tenant slug + email (scripts, evals and tests acting as real users)."""
    row = await conn.fetchrow(
        "SELECT u.id, u.tenant_id FROM users u JOIN tenants t ON t.id = u.tenant_id "
        "WHERE t.slug = $1 AND u.email = $2",
        tenant_slug,
        email,
    )
    if row is None:
        raise AuthenticationFailed(f"no user {email} in tenant {tenant_slug}")
    return await load_auth_context(conn, row["id"], row["tenant_id"])


async def get_auth_context(request: Request) -> AuthContext:
    credentials: HTTPAuthorizationCredentials | None = await _bearer(request)
    if credentials is None:
        raise AuthenticationFailed("missing bearer token")
    user_id, tenant_id = verify_token(request.app.state.settings, credentials.credentials)
    async with request.app.state.pool.acquire() as conn:
        return await load_auth_context(conn, user_id, tenant_id)


ADMIN_ROLE = "admin"


async def require_admin(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> AuthContext:
    """The admin role as the database holds it NOW (correction H), never a claim in the token.
    Admin is per tenant: it manages the caller's own tenant and grants no read access to chunks."""
    if ADMIN_ROLE not in auth.roles:
        raise Forbidden("admin role required")
    return auth
