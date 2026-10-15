"""Domain types and constants."""
from __future__ import annotations

from dataclasses import dataclass

ROLES = ("viewer", "analyst", "admin")
ROLE_LEVEL = {"viewer": 1, "analyst": 2, "admin": 3}
CLASSIFICATIONS = ("internal", "confidential")


@dataclass(frozen=True)
class Tenant:
    id: str
    name: str


@dataclass(frozen=True)
class User:
    """An authenticated principal. The service layer treats this as trusted input."""

    id: str
    tenant_id: str
    email: str
    role: str


def role_level(role: str) -> int:
    """Numeric rank for a role. Unknown roles rank below every real role (fail closed)."""
    return ROLE_LEVEL.get(role, 0)
