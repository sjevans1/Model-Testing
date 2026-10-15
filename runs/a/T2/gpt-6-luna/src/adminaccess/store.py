"""sqlite persistence for the admin console."""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    email TEXT NOT NULL,
    role TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    actor_id TEXT,
    tenant_id TEXT,
    action TEXT NOT NULL,
    object_id TEXT,
    detail TEXT
);
"""


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return list(self._conn.execute(sql, params).fetchall())

    def add_user(self, user_id: str, tenant_id: str, email: str, role: str) -> None:
        self._conn.execute(
            "INSERT INTO users(id, tenant_id, email, role, version, updated_at)"
            " VALUES (?, ?, ?, ?, 1, ?)",
            (user_id, tenant_id, email, role, time.time()),
        )
        self._conn.commit()

    def audit(self, actor_id: str, tenant_id: str, action: str, object_id: str, detail: str = "") -> None:
        self._conn.execute(
            "INSERT INTO audit(at, actor_id, tenant_id, action, object_id, detail)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), actor_id, tenant_id, action, object_id, detail),
        )
        self._conn.commit()
