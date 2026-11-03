"""Admin API (correction H): the caller's own tenant and its users and their roles.

Every route requires the admin role, read from the database per request (gateway.deps.require_admin).
The tenant comes only from the token: no path or body ever names a tenant, and every statement is
scoped by `tenant_id = <caller's tenant>`. Another tenant's user id therefore behaves exactly like an
id that does not exist (404), so an admin cannot even confirm that it exists elsewhere.

Not here, by design: creating or deleting tenants (an operator action, not a tenant admin's), and
document ACL changes (they arrive with the ingest endpoint and must wipe the tenant's cache, K).
"""

import logging
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Request, Response

from gateway.deps import AuthContext, require_admin
from gateway.errors import AdminTargetNotFound, DuplicateUser
from gateway.models.admin import TenantOut, TenantUpdate, UserCreate, UserOut, UserUpdate

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin")
Admin = Annotated[AuthContext, Depends(require_admin)]


def _user(row: asyncpg.Record | None) -> UserOut:
    if row is None:
        raise AdminTargetNotFound("no such user in this tenant")
    return UserOut(**dict(row))


@router.get("/tenant", response_model=TenantOut)
async def get_tenant(request: Request, admin: Admin) -> TenantOut:
    async with request.app.state.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT slug, name, created_at FROM tenants WHERE id = $1", admin.tenant_id)
    return TenantOut(**dict(row))


@router.patch("/tenant", response_model=TenantOut)
async def update_tenant(body: TenantUpdate, request: Request, admin: Admin) -> TenantOut:
    async with request.app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE tenants SET name = $2 WHERE id = $1 RETURNING slug, name, created_at",
            admin.tenant_id,
            body.name,
        )
    log.info("admin %s renamed tenant %s", admin.user_id, admin.tenant_id)
    return TenantOut(**dict(row))


@router.get("/users", response_model=list[UserOut])
async def list_users(request: Request, admin: Admin) -> list[UserOut]:
    async with request.app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, email, roles, clearance, created_at FROM users WHERE tenant_id = $1 ORDER BY email",
            admin.tenant_id,
        )
    return [UserOut(**dict(r)) for r in rows]


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, request: Request, admin: Admin) -> UserOut:
    async with request.app.state.pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                "INSERT INTO users (tenant_id, email, roles, clearance) VALUES ($1, $2, $3, $4) "
                "RETURNING id, email, roles, clearance, created_at",
                admin.tenant_id,
                body.email,
                body.roles,
                body.clearance,
            )
        except asyncpg.UniqueViolationError as exc:
            raise DuplicateUser("a user with this email already exists in this tenant") from exc
    user = _user(row)
    log.info("admin %s created user %s in tenant %s", admin.user_id, user.id, admin.tenant_id)
    return user


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: UUID, request: Request, admin: Admin) -> UserOut:
    async with request.app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, roles, clearance, created_at FROM users WHERE id = $1 AND tenant_id = $2",
            user_id,
            admin.tenant_id,
        )
    return _user(row)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: UUID, body: UserUpdate, request: Request, admin: Admin) -> UserOut:
    # coalesce keeps a field the body leaves out; roles and clearance take effect on the user's next
    # request, because AuthContext is reloaded from this table every time.
    async with request.app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE users SET roles = coalesce($3, roles), clearance = coalesce($4, clearance) "
            "WHERE id = $1 AND tenant_id = $2 RETURNING id, email, roles, clearance, created_at",
            user_id,
            admin.tenant_id,
            body.roles,
            body.clearance,
        )
    user = _user(row)
    log.info("admin %s updated user %s in tenant %s", admin.user_id, user.id, admin.tenant_id)
    return user


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: UUID, request: Request, admin: Admin) -> Response:
    async with request.app.state.pool.acquire() as conn:
        deleted = await conn.fetchval(
            "DELETE FROM users WHERE id = $1 AND tenant_id = $2 RETURNING id", user_id, admin.tenant_id
        )
    if deleted is None:
        raise AdminTargetNotFound("no such user in this tenant")
    log.info("admin %s deleted user %s in tenant %s", admin.user_id, user_id, admin.tenant_id)
    return Response(status_code=204)
