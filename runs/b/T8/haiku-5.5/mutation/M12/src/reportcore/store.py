"""SQLite persistence. All access goes through this class; nothing else opens the DB."""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    email TEXT NOT NULL,
    role TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    classification TEXT NOT NULL DEFAULT 'internal',
    created_at REAL NOT NULL,
    current_version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS dataset_versions (
    dataset_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (dataset_id, version)
);
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    classification TEXT NOT NULL DEFAULT 'internal',
    created_at REAL NOT NULL,
    revoked_at REAL,
    revoked_by TEXT,
    revoke_reason TEXT
);
CREATE TABLE IF NOT EXISTS report_snapshots (
    report_id TEXT PRIMARY KEY REFERENCES reports(id),
    payload_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    actor_id TEXT,
    tenant_id TEXT,
    action TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT,
    detail TEXT
);
"""


class Store:
    """Thin wrapper over sqlite3 with the schema applied."""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, tuple(params))

    def fetchone(self, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
        return self._conn.execute(sql, tuple(params)).fetchone()

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return list(self._conn.execute(sql, tuple(params)).fetchall())

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def seed_tenant(self, tenant_id: str, name: str) -> None:
        self.execute("INSERT OR REPLACE INTO tenants(id, name) VALUES (?, ?)", (tenant_id, name))
        self.commit()

    def seed_user(self, user_id: str, tenant_id: str, email: str, role: str) -> None:
        self.execute(
            "INSERT OR REPLACE INTO users(id, tenant_id, email, role) VALUES (?, ?, ?, ?)",
            (user_id, tenant_id, email, role),
        )
        self.commit()

    def add_audit(
        self,
        actor_id: Optional[str],
        action: str,
        object_type: str,
        object_id: Optional[str],
        tenant_id: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        """Append one audit row. Every mutation and every privileged read goes through here."""
        self.execute(
            "INSERT INTO audit(at, actor_id, tenant_id, action, object_type, object_id, detail)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), actor_id, tenant_id, action, object_type, object_id, detail),
        )

    def audit_rows(self, object_id: Optional[str] = None) -> list[sqlite3.Row]:
        if object_id is None:
            return self.fetchall("SELECT * FROM audit ORDER BY id")
        return self.fetchall("SELECT * FROM audit WHERE object_id = ? ORDER BY id", (object_id,))
