"""The ACL predicate: the only place it is written (CLAUDE.md invariants 1-3, code conventions).

A chunk is readable by a caller when it belongs to the caller's tenant, its allowed_roles is empty
(all roles in the tenant) or shares a role with the caller, and its min_clearance does not exceed
the caller's clearance. Roles and clearance come from the database at query time (AuthContext),
never from token claims.

The predicate is applied inside the SQL WHERE clause of every retrieval path. It is composed from
constant text only: the table alias is checked against an identifier pattern and the parameter
positions are integers; tenant, roles and clearance are always bound parameters, never interpolated.
"""

import re
from dataclasses import dataclass
from uuid import UUID

_ALIAS = re.compile(r"^[a-z_][a-z0-9_]{0,30}$")


@dataclass(frozen=True)
class AclFilter:
    tenant_id: UUID
    roles: tuple[str, ...]
    clearance: int

    def params(self) -> tuple[UUID, list[str], int]:
        """Bind values, in the order acl_predicate expects them."""
        return self.tenant_id, list(self.roles), self.clearance


def acl_predicate(alias: str, first_param: int) -> str:
    """SQL boolean over table `alias`, binding tenant, roles and clearance at $first_param .. +2."""
    if not _ALIAS.match(alias) or not isinstance(first_param, int) or first_param < 1:
        raise ValueError(f"invalid alias or parameter position: {alias!r}, {first_param!r}")
    tenant, roles, clearance = first_param, first_param + 1, first_param + 2
    return (
        f"({alias}.tenant_id = ${tenant}"
        f" AND (cardinality({alias}.allowed_roles) = 0 OR {alias}.allowed_roles && ${roles}::text[])"
        f" AND {alias}.min_clearance <= ${clearance})"
    )
