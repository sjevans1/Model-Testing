"""Authorization primitives. Every service entry point calls into this module."""
from __future__ import annotations

from .errors import Forbidden, NotFound
from .models import User, role_level


def require_role(actor: User, minimum: str) -> None:
    """Raise Forbidden unless *actor* holds at least *minimum*."""
    if role_level(actor.role) < role_level(minimum):
        raise Forbidden(f"role {actor.role!r} may not perform this action")


def may_read_classification(actor: User, classification: str) -> bool:
    """Confidential objects are admin-only; internal objects are tenant-readable."""
    if classification == "confidential":
        return role_level(actor.role) >= role_level("admin")
    return True


def require_tenant(actor: User, tenant_id: str) -> None:
    """Tenant checks never disclose existence: a foreign tenant is a NotFound, not a Forbidden."""
    if not tenant_id or tenant_id != actor.tenant_id:
        raise NotFound("no such object")
