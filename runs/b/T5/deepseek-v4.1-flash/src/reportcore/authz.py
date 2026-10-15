"""Authorization primitives. Every service entry point calls into this module."""
from __future__ import annotations

from .errors import Forbidden, NotFound
from .models import CLASSIFICATIONS, ROLE_LEVEL, User, role_level


def is_known_role(role: object) -> bool:
    """True only for a role this build recognises.

    Anything else (missing, empty, whitespace, different case, invented) is not a
    role at all and is granted nothing: the primitives below fail closed on it.
    """
    return isinstance(role, str) and role in ROLE_LEVEL


def require_role(actor: User, minimum: str) -> None:
    """Raise Forbidden unless *actor* holds at least *minimum*.

    D4 fixed: an unrecognised role is refused outright instead of slipping past the
    rank comparison (``ROLE_LEVEL.get(role, 0)`` used to make it fail open).
    """
    if not is_known_role(actor.role):
        raise Forbidden(f"role {actor.role!r} is not a recognised role")
    if role_level(actor.role) < role_level(minimum):
        raise Forbidden(f"role {actor.role!r} may not perform this action")


def may_read_classification(actor: User, classification: str) -> bool:
    """Confidential objects are admin-only; internal objects are tenant-readable.

    Fails closed twice over: an unrecognised role may read nothing, and an
    unrecognised classification is not readable (rather than being treated as
    the least sensitive one).
    """
    if not is_known_role(actor.role):
        return False
    if classification == "confidential":
        return role_level(actor.role) >= role_level("admin")
    return classification in CLASSIFICATIONS


def require_tenant(actor: User, tenant_id: str) -> None:
    """Tenant checks never disclose existence: a foreign tenant is a NotFound, not a Forbidden."""
    if not tenant_id or tenant_id != actor.tenant_id:
        raise NotFound("no such object")
