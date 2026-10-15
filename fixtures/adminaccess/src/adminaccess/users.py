"""User access service. Authorization here is the real boundary; the UI is not."""
from __future__ import annotations

import time
from dataclasses import dataclass

from .store import Store

ROLES = ("viewer", "analyst", "admin")


class Error(Exception):
    pass


class ValidationError(Error):
    pass


class Forbidden(Error):
    pass


class NotFound(Error):
    pass


class StaleVersion(Error):
    """The client tried to write against a version it no longer holds."""


@dataclass(frozen=True)
class Actor:
    id: str
    tenant_id: str
    role: str


class UserService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def get_user(self, actor: Actor, user_id: str) -> dict:
        row = self.store.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        if row is None or row["tenant_id"] != actor.tenant_id:
            raise NotFound("no such user")
        return dict(row)

    def list_users(self, actor: Actor) -> list[dict]:
        rows = self.store.fetchall(
            "SELECT id, email, role, version FROM users WHERE tenant_id = ? ORDER BY email",
            (actor.tenant_id,),
        )
        return [dict(r) for r in rows]

    def change_role(self, actor: Actor, user_id: str, new_role: str, seen_version: int | None = None) -> dict:
        """Persist a role change immediately. Returns the updated row."""
        if new_role not in ROLES:
            raise ValidationError(f"role must be one of {ROLES}")
        row = self.store.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        if row is None or row["tenant_id"] != actor.tenant_id:
            raise NotFound("no such user")
        if seen_version is not None and int(seen_version) != int(row["version"]):
            raise StaleVersion(f"expected version {row['version']}, got {seen_version}")
        self.store.conn.execute(
            "UPDATE users SET role = ?, version = version + 1, updated_at = ? WHERE id = ?",
            (new_role, time.time(), user_id),
        )
        self.store.audit(actor.id, actor.tenant_id, "user.role_change", user_id, f"{row['role']}->{new_role}")
        return self.get_user(actor, user_id)
