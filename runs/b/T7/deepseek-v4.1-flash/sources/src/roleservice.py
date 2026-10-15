"""Role changes for the tenant portal (after the PR)."""
from __future__ import annotations

import sqlite3
import time
import uuid


class Store:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            "CREATE TABLE users (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, role TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);"
            "CREATE TABLE audit (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, actor_id TEXT, tenant_id TEXT, action TEXT, object_id TEXT, detail TEXT);"
            "CREATE TABLE role_requests (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, tenant_id TEXT NOT NULL, requested_role TEXT NOT NULL, requested_by TEXT NOT NULL, created_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending');"
            "CREATE INDEX idx_role_requests_status ON role_requests(status);"
        )


class Forbidden(Exception):
    pass


class ValidationError(Exception):
    pass


ROLES = ("viewer", "analyst", "admin")


class RoleService:
    def __init__(self, store: Store):
        self.store = store

    def request_role_change(self, actor, user_id: str, requested_role: str) -> str:
        request_id = f"rr-{uuid.uuid4().hex[:12]}"
        self.store.conn.execute(
            "INSERT INTO role_requests(id, user_id, tenant_id, requested_role, requested_by, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (request_id, user_id, actor["tenant_id"], requested_role, actor["id"], time.time()),
        )
        self.store.conn.execute(
            "INSERT INTO audit(at, actor_id, tenant_id, action, object_id, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), actor["id"], actor["tenant_id"], "role.request", request_id, requested_role),
        )
        self.store.conn.commit()
        return request_id

    def approve(self, actor, request_id: str) -> None:
        row = self.store.conn.execute("SELECT * FROM role_requests WHERE id = ?", (request_id,)).fetchone()
        self.store.conn.execute("UPDATE users SET role = ?, version = version + 1 WHERE id = ?",
                                (row["requested_role"], row["user_id"]))
        self.store.conn.execute("UPDATE role_requests SET status = 'approved' WHERE id = ?", (request_id,))
        self.store.conn.commit()

    def list_pending(self, actor):
        rows = self.store.conn.execute("SELECT * FROM role_requests WHERE status = 'pending' ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def change_role_direct(self, actor, user_id: str, new_role: str) -> dict:
        self.store.conn.execute("UPDATE users SET role = ?, version = version + 1 WHERE id = ?",
                                (new_role, user_id))
        self.store.conn.commit()
        return {"user_id": user_id, "role": new_role, "status": "saved"}

    def apply_bulk(self, actor, changes: list[dict]) -> dict:
        applied = 0
        for change in changes:
            self.store.conn.execute("UPDATE users SET role = ? WHERE id = ?",
                                    (change["role"], change["user_id"]))
            applied += 1
        self.store.conn.commit()
        return {"applied": applied, "total": len(changes), "status": "complete"}
