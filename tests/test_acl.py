"""The ACL predicate: its text, its validation, and its truth table evaluated by Postgres itself."""

from uuid import UUID, uuid4

import asyncpg
import pytest

from gateway.security.acl import AclFilter, acl_predicate


def test_predicate_binds_every_value_and_interpolates_none() -> None:
    sql = acl_predicate("c", 3)
    assert sql == (
        "(c.tenant_id = $3 AND (cardinality(c.allowed_roles) = 0 OR c.allowed_roles && $4::text[])"
        " AND c.min_clearance <= $5)"
    )


@pytest.mark.parametrize("alias", ["", "C", "c; DROP TABLE chunks", "c.x", "1c", "c--"])
def test_alias_must_be_a_plain_identifier(alias: str) -> None:
    with pytest.raises(ValueError):
        acl_predicate(alias, 1)


@pytest.mark.parametrize("position", [0, -1, "3", 1.5])
def test_parameter_position_must_be_a_positive_int(position: object) -> None:
    with pytest.raises(ValueError):
        acl_predicate("c", position)  # type: ignore[arg-type]


def test_filter_params_are_in_predicate_order() -> None:
    tid = uuid4()
    assert AclFilter(tenant_id=tid, roles=("employee", "hr"), clearance=2).params() == (
        tid,
        ["employee", "hr"],
        2,
    )


TENANT = UUID("00000000-0000-0000-0000-00000000000a")
OTHER = UUID("00000000-0000-0000-0000-00000000000b")


@pytest.mark.parametrize(
    ("chunk_tenant", "allowed_roles", "min_clearance", "roles", "clearance", "readable"),
    [
        (TENANT, [], 0, ["employee"], 0, True),  # empty roles = every role in the tenant
        (OTHER, [], 0, ["employee"], 3, False),  # another tenant, whatever the roles
        (TENANT, ["hr"], 0, ["employee"], 3, False),  # role missing
        (TENANT, ["hr", "legal"], 0, ["employee", "legal"], 0, True),  # any shared role suffices
        (TENANT, ["hr"], 2, ["hr"], 1, False),  # role present, clearance too low
        (TENANT, ["hr"], 2, ["hr"], 2, True),  # clearance equal is enough
        (TENANT, [], 3, ["employee"], 2, False),  # clearance applies to unrestricted roles too
        (TENANT, ["hr"], 0, [], 3, False),  # a user with no roles reads only role-free chunks
    ],
)
async def test_truth_table_in_postgres(
    pool: asyncpg.Pool,
    chunk_tenant: UUID,
    allowed_roles: list[str],
    min_clearance: int,
    roles: list[str],
    clearance: int,
    readable: bool,
) -> None:
    sql = (
        "SELECT "
        + acl_predicate("c", 4)
        + " FROM (SELECT $1::uuid AS tenant_id, $2::text[] AS allowed_roles, "
        "$3::int AS min_clearance) c"
    )
    flt = AclFilter(tenant_id=TENANT, roles=tuple(roles), clearance=clearance)
    async with pool.acquire() as conn:
        assert await conn.fetchval(sql, chunk_tenant, allowed_roles, min_clearance, *flt.params()) is readable
