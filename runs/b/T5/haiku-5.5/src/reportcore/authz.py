"""Authorization primitives. Every service entry point calls into this module."""
from __future__ import annotations

from .errors import Forbidden, NotFound
from .models import ROLE_LEVEL, User, role_level


def require_role(actor: User, minimum: str) -> None:
    """Raise Forbidden unless *actor* holds at least *minimum*. Unknown roles are denied."""
    if minimum not in ROLE_LEVEL:
        raise ValueError(f"unknown minimum role {minimum!r}")
    if actor.role not in ROLE_LEVEL or role_level(actor.role) < role_level(minimum):
        raise Forbidden(f"role {actor.role!r} may not perform this action")


def may_read_classification(actor: User, classification: str) -> bool:
    """Confidential objects are admin-only; internal objects are tenant-readable.

    Fails closed: an unrecognised actor role or an unrecognised classification is not readable.
    """
    if actor.role not in ROLE_LEVEL:
        return False
    if classification == "confidential":
        return role_level(actor.role) >= role_level("admin")
    if classification == "internal":
        return True
    return False


def require_tenant(actor: User, tenant_id: str) -> None:
    """Tenant checks never disclose existence: a foreign tenant is a NotFound, not a Forbidden."""
    if not tenant_id or tenant_id != actor.tenant_id:
        raise NotFound("no such object")
