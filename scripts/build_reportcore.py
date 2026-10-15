#!/usr/bin/env python3
"""Build the reportcore fixture family for BENCH-MODEL-001.

Emits three variants of the same multi-tenant backend from one source of truth:
  fixtures/reportcore_t3  -> Saved Reports feature STUBBED (T3: implement it)
  fixtures/reportcore_t5  -> Saved Reports feature IMPLEMENTED with seeded defects (T5: find/fix)
  fixtures/reportcore_t8  -> same defective tree + CLAIMS.md (T8: write discriminating tests)
Plus hidden assets:
  harness/hidden/            acceptance + negative tests, kept out of candidate trees
  harness/reference/service.py  a correct implementation (proof of solvability + T8 mutation target)

stdlib only. Run:  python3 scripts/build_reportcore.py
"""
from __future__ import annotations

import pathlib
import shutil

BENCH = pathlib.Path(__file__).resolve().parent.parent
FIX = BENCH / "fixtures"
HID = BENCH / "harness" / "hidden"
REF = BENCH / "harness" / "reference"

# --------------------------------------------------------------------------------------
# Shared (correct) files
# --------------------------------------------------------------------------------------
ERRORS = '''"""Exception types. Cross-tenant access must be indistinguishable from a missing object."""
from __future__ import annotations


class ReportCoreError(Exception):
    """Base class for every error this package raises."""


class NotFound(ReportCoreError):
    """No such object *visible to this actor* (also used for cross-tenant access)."""


class Forbidden(ReportCoreError):
    """The actor may see the object but is not allowed to perform the action."""


class ValidationError(ReportCoreError):
    """The request itself is malformed."""


class Conflict(ReportCoreError):
    """The request conflicts with current state (e.g. optimistic-concurrency mismatch)."""
'''

MODELS = '''"""Domain types and constants."""
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
'''

STORE = '''"""SQLite persistence. All access goes through this class; nothing else opens the DB."""
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
'''

AUTHZ = '''"""Authorization primitives. Every service entry point calls into this module."""
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
'''

SERVICE_COMMON = '''"""Service layer. All business rules live here; the store does no authorization."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from .authz import may_read_classification, require_role, require_tenant
from .errors import Conflict, Forbidden, NotFound, ValidationError
from .models import CLASSIFICATIONS, User, role_level
from .store import Store


def _now() -> float:
    return time.time()


def _new_id() -> str:
    return uuid.uuid4().hex


def _canonical(payload: dict) -> tuple[str, str]:
    """Canonical JSON + content hash. Two equal payloads always hash equal."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return blob, hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _validate_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("name must be a non-empty string")
    return name.strip()


def _validate_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("payload must be an object")
    return payload


def _validate_classification(classification: Any) -> str:
    if classification not in CLASSIFICATIONS:
        raise ValidationError(f"classification must be one of {CLASSIFICATIONS}")
    return classification


class DatasetRegistry:
    """Reference feature: immutable versions, tenant scope, role gate, audit.

    The SavedReportsService below follows exactly these conventions.
    """

    def __init__(self, store: Store) -> None:
        self.store = store

    def save_dataset(
        self, actor: User, name: str, payload: dict, classification: str = "internal"
    ) -> str:
        name = _validate_name(name)
        payload = _validate_payload(payload)
        classification = _validate_classification(classification)
        require_role(actor, "analyst")
        if classification == "confidential":
            require_role(actor, "admin")

        dataset_id = _new_id()
        blob, digest = _canonical(payload)
        with self.store.conn:
            self.store.execute(
                "INSERT INTO datasets(id, tenant_id, owner_id, name, classification, created_at,"
                " current_version) VALUES (?, ?, ?, ?, ?, ?, 1)",
                (dataset_id, actor.tenant_id, actor.id, name, classification, _now()),
            )
            self.store.execute(
                "INSERT INTO dataset_versions(dataset_id, version, payload_json, content_hash,"
                " created_at) VALUES (?, 1, ?, ?, ?)",
                (dataset_id, blob, digest, _now()),
            )
            self.store.add_audit(actor.id, "dataset.save", "dataset", dataset_id, actor.tenant_id, digest)
        return dataset_id

    def get_dataset(self, actor: User, dataset_id: str) -> dict:
        row = self.store.fetchone("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
        if row is None:
            raise NotFound("no such object")
        require_tenant(actor, row["tenant_id"])
        if not may_read_classification(actor, row["classification"]):
            raise Forbidden("classification not readable by this role")
        version = self.store.fetchone(
            "SELECT * FROM dataset_versions WHERE dataset_id = ? ORDER BY version DESC LIMIT 1",
            (dataset_id,),
        )
        self.store.add_audit(actor.id, "dataset.read", "dataset", dataset_id, actor.tenant_id)
        self.store.commit()
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "owner_id": row["owner_id"],
            "name": row["name"],
            "classification": row["classification"],
            "version": version["version"],
            "content_hash": version["content_hash"],
            "payload": json.loads(version["payload_json"]),
        }

    def list_datasets(self, actor: User) -> list[dict]:
        rows = self.store.fetchall(
            "SELECT id, name, classification, owner_id FROM datasets WHERE tenant_id = ?"
            " ORDER BY name",
            (actor.tenant_id,),
        )
        visible = [dict(r) for r in rows if may_read_classification(actor, r["classification"])]
        self.store.add_audit(actor.id, "dataset.list", "dataset", None, actor.tenant_id)
        self.store.commit()
        return visible


'''

# --------------------------------------------------------------------------------------
# SavedReportsService variants
# --------------------------------------------------------------------------------------
SR_STUB = '''class SavedReportsService:
    """Saved Reports. NOT IMPLEMENTED: this is the feature under construction.

    The report and report_snapshots tables already exist in the schema. Follow the
    conventions demonstrated by DatasetRegistry: validate first, gate by role, scope
    every query by the actor\'s tenant, write an audit row for every mutation and
    privileged read, and store immutable content as canonical JSON plus sha256.
    """

    def __init__(self, store: Store) -> None:
        self.store = store

    def save_report(
        self, actor: User, name: str, payload: dict, classification: str = "internal"
    ) -> str:
        raise NotImplementedError("SavedReportsService.save_report is not implemented")

    def get_report(self, actor: User, report_id: str) -> dict:
        raise NotImplementedError("SavedReportsService.get_report is not implemented")

    def list_reports(self, actor: User) -> list[dict]:
        raise NotImplementedError("SavedReportsService.list_reports is not implemented")

    def revoke_report(self, actor: User, report_id: str, reason: str = "") -> None:
        raise NotImplementedError("SavedReportsService.revoke_report is not implemented")
'''

SR_DEFECTIVE = '''class SavedReportsService:
    """Saved Reports, as shipped by the previous contractor.

    CLAIMED: immutable snapshots, tenant-scoped access, confidentiality enforcement,
    role checks on revocation, audit trail.
    """

    def __init__(self, store: Store) -> None:
        self.store = store

    def save_report(
        self, actor: User, name: str, payload: dict, classification: str = "internal"
    ) -> str:
        name = _validate_name(name)
        payload = _validate_payload(payload)
        # DEFECT D5: trusts a client-supplied tenant id over the authenticated actor.
        tenant_id = str(payload.get("tenant_id") or actor.tenant_id)
        report_id = _new_id()
        blob, digest = _canonical(payload)
        with self.store.conn:
            self.store.execute(
                "INSERT INTO reports(id, tenant_id, owner_id, name, classification, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (report_id, tenant_id, actor.id, name, classification, _now()),
            )
            self.store.execute(
                "INSERT INTO report_snapshots(report_id, payload_json, content_hash, created_at)"
                " VALUES (?, ?, ?, ?)",
                (report_id, blob, digest, _now()),
            )
            self.store.add_audit(actor.id, "report.save", "report", report_id, tenant_id, digest)
        return report_id

    def get_report(self, actor: User, report_id: str) -> dict:
        # DEFECT D1: no tenant scope on the read.
        row = self.store.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))
        if row is None:
            raise NotFound("no such object")
        snapshot = self.store.fetchone(
            "SELECT * FROM report_snapshots WHERE report_id = ?", (report_id,)
        )
        if snapshot is None:
            raise NotFound("no such object")
        # DEFECT D3: classification is never consulted.
        self.store.add_audit(actor.id, "report.read", "report", report_id, row["tenant_id"])
        self.store.commit()
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "owner_id": row["owner_id"],
            "name": row["name"],
            "classification": row["classification"],
            "revoked": row["revoked_at"] is not None,
            "content_hash": snapshot["content_hash"],
            "payload": json.loads(snapshot["payload_json"]),
        }

    def list_reports(self, actor: User) -> list[dict]:
        rows = self.store.fetchall(
            "SELECT id, tenant_id, owner_id, name, classification, revoked_at FROM reports"
            " ORDER BY name"
        )
        # DEFECT D6: lists every tenant, and revoked rows leak as "saved" entries.
        out = [
            {
                "id": r["id"],
                "name": r["name"],
                "classification": r["classification"],
                "owner_id": r["owner_id"],
                "revoked": False,
            }
            for r in rows
        ]
        self.store.add_audit(actor.id, "report.list", "report", None, actor.tenant_id)
        self.store.commit()
        return out

    def revoke_report(self, actor: User, report_id: str, reason: str = "") -> None:
        # DEFECT D2: exists-by-id only. No tenant check, no role check.
        row = self.store.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))
        if row is None:
            raise NotFound("no such object")
        with self.store.conn:
            self.store.execute(
                "UPDATE reports SET revoked_at = ?, revoked_by = ?, revoke_reason = ?"
                " WHERE id = ?",
                (_now(), actor.id, reason, report_id),
            )
            self.store.add_audit(actor.id, "report.revoke", "report", report_id, row["tenant_id"])

    def save_batch(self, actor: User, items: list) -> dict:
        """Save several reports at once and report how the batch went."""
        saved = []
        for item in items:
            try:
                saved.append(
                    self.save_report(
                        actor,
                        (item or {}).get("name", ""),
                        (item or {}).get("payload") or {},
                        (item or {}).get("classification", "internal"),
                    )
                )
            except Exception:  # noqa: BLE001
                # DEFECT D8: per-item failures are swallowed, and the batch always
                # reports itself complete with the requested item count.
                pass
        return {"applied": len(items), "saved": saved, "status": "complete"}
'''

SR_CORRECT = '''class SavedReportsService:
    """Saved Reports: immutable snapshot, tenant-scoped, role gated, audited."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def save_report(
        self, actor: User, name: str, payload: dict, classification: str = "internal"
    ) -> str:
        name = _validate_name(name)
        payload = _validate_payload(payload)
        classification = _validate_classification(classification)
        require_role(actor, "analyst")
        if classification == "confidential":
            require_role(actor, "admin")

        report_id = _new_id()
        blob, digest = _canonical(payload)
        with self.store.conn:
            self.store.execute(
                "INSERT INTO reports(id, tenant_id, owner_id, name, classification, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (report_id, actor.tenant_id, actor.id, name, classification, _now()),
            )
            self.store.execute(
                "INSERT INTO report_snapshots(report_id, payload_json, content_hash, created_at)"
                " VALUES (?, ?, ?, ?)",
                (report_id, blob, digest, _now()),
            )
            self.store.add_audit(
                actor.id, "report.save", "report", report_id, actor.tenant_id, digest
            )
        return report_id

    def _row_or_notfound(self, actor: User, report_id: str):
        row = self.store.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))
        if row is None:
            raise NotFound("no such object")
        require_tenant(actor, row["tenant_id"])
        return row

    def get_report(self, actor: User, report_id: str) -> dict:
        row = self._row_or_notfound(actor, report_id)
        if not may_read_classification(actor, row["classification"]):
            raise Forbidden("classification not readable by this role")
        if row["revoked_at"] is not None and role_level(actor.role) < role_level("admin"):
            raise Forbidden("report is revoked")
        snapshot = self.store.fetchone(
            "SELECT * FROM report_snapshots WHERE report_id = ?", (report_id,)
        )
        if snapshot is None:
            raise NotFound("no such object")
        self.store.add_audit(actor.id, "report.read", "report", report_id, row["tenant_id"])
        self.store.commit()
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "owner_id": row["owner_id"],
            "name": row["name"],
            "classification": row["classification"],
            "revoked": row["revoked_at"] is not None,
            "content_hash": snapshot["content_hash"],
            "payload": json.loads(snapshot["payload_json"]),
        }

    def list_reports(self, actor: User) -> list[dict]:
        rows = self.store.fetchall(
            "SELECT id, owner_id, name, classification, revoked_at FROM reports"
            " WHERE tenant_id = ? ORDER BY name",
            (actor.tenant_id,),
        )
        out = []
        for r in rows:
            if not may_read_classification(actor, r["classification"]):
                continue
            if r["revoked_at"] is not None:
                continue
            out.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "classification": r["classification"],
                    "owner_id": r["owner_id"],
                    "revoked": False,
                }
            )
        self.store.add_audit(actor.id, "report.list", "report", None, actor.tenant_id)
        self.store.commit()
        return out

    def revoke_report(self, actor: User, report_id: str, reason: str = "") -> None:
        row = self._row_or_notfound(actor, report_id)
        report_id = row["id"]
        if actor.id != row["owner_id"]:
            require_role(actor, "admin")
        if not may_read_classification(actor, row["classification"]):
            raise Forbidden("classification not readable by this role")
        with self.store.conn:
            self.store.execute(
                "UPDATE reports SET revoked_at = ?, revoked_by = ?, revoke_reason = ? WHERE id = ?",
                (_now(), actor.id, reason, report_id),
            )
            self.store.add_audit(actor.id, "report.revoke", "report", report_id, row["tenant_id"])

    def save_batch(self, actor: User, items: list) -> dict:
        """Save several reports and report the true outcome of the batch."""
        saved: list[str] = []
        failures: list[dict] = []
        for index, item in enumerate(items):
            try:
                saved.append(
                    self.save_report(
                        actor,
                        (item or {}).get("name", ""),
                        (item or {}).get("payload") or {},
                        (item or {}).get("classification", "internal"),
                    )
                )
            except (ValidationError, Forbidden) as exc:
                failures.append({"index": index, "error": type(exc).__name__, "message": str(exc)})
        return {
            "attempted": len(items),
            "applied": len(saved),
            "failed": len(failures),
            "saved": saved,
            "failures": failures,
            "status": "complete" if not failures else "partial",
        }
'''

README = """# reportcore

Multi-tenant knowledge/report backend used by the OpenJM tenant portal. Pure stdlib
(sqlite3 + unittest), no third-party dependencies.

## Layout

```
src/reportcore/errors.py    exception types
src/reportcore/models.py    User/Tenant dataclasses, role ranks, classifications
src/reportcore/store.py     sqlite schema + Store wrapper (the only DB access point)
src/reportcore/authz.py     role and tenant checks
src/reportcore/service.py   DatasetRegistry (reference feature) + SavedReportsService
tests/                      visible smoke tests
run_checks.sh               python3 -m unittest discover -s tests -v
```

## Conventions (follow these)

1. Validate input in the service before touching the store; raise `ValidationError`.
2. Gate by role with `authz.require_role(actor, minimum)` where `minimum` is
   `viewer` < `analyst` < `admin`.
3. Scope **every** query by `actor.tenant_id`. A foreign tenant is a `NotFound`, never a
   `Forbidden`: errors must not disclose that an object exists elsewhere.
4. Immutable content is stored as canonical JSON plus a sha256 digest. Revocation flips a
   status column; it never edits or deletes the stored snapshot.
5. Write one audit row per mutation and per privileged read via `store.add_audit(...)`.
   Actions are `"<object>.<verb>"`, e.g. `dataset.save`, `report.revoke`.
6. `User` is authenticated and trusted; anything in a `payload` is caller-controlled and
   must never decide tenant, owner or permissions.

## Run

```sh
sh run_checks.sh
```
"""

__init__ = '''"""reportcore: multi-tenant knowledge/report backend."""
from .authz import may_read_classification, require_role, require_tenant
from .errors import Conflict, Forbidden, NotFound, ReportCoreError, ValidationError
from .models import CLASSIFICATIONS, ROLE_LEVEL, ROLES, Tenant, User, role_level
from .service import DatasetRegistry, SavedReportsService
from .store import Store

__all__ = [
    "CLASSIFICATIONS", "ROLE_LEVEL", "ROLES", "Conflict", "DatasetRegistry", "Forbidden",
    "NotFound", "ReportCoreError", "SavedReportsService", "Store", "Tenant", "User",
    "ValidationError", "may_read_classification", "require_role", "require_tenant", "role_level",
]
'''

VISIBLE_TESTS = '''"""Visible smoke tests. These pass on the shipped tree; add your own tests alongside."""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from reportcore import DatasetRegistry, Store, User  # noqa: E402


def make_store() -> Store:
    store = Store()
    store.seed_tenant("t1", "Tenant One")
    store.seed_tenant("t2", "Tenant Two")
    return store


class TestDatasetRegistry(unittest.TestCase):
    def test_save_then_get_roundtrips(self):
        store = make_store()
        registry = DatasetRegistry(store)
        analyst = User(id="u1", tenant_id="t1", email="a@t1", role="analyst")
        dataset_id = registry.save_dataset(analyst, "Sales", {"rows": 3})
        got = registry.get_dataset(analyst, dataset_id)
        self.assertEqual(got["payload"], {"rows": 3})
        self.assertEqual(got["tenant_id"], "t1")

    def test_viewer_cannot_save(self):
        store = make_store()
        registry = DatasetRegistry(store)
        viewer = User(id="u2", tenant_id="t1", email="v@t1", role="viewer")
        with self.assertRaises(Exception):
            registry.save_dataset(viewer, "Nope", {"rows": 1})


if __name__ == "__main__":
    unittest.main()
'''

RUN_CHECKS = '''#!/bin/sh
# Focused verification for this repository.
set -eu
cd "$(dirname "$0")"
PYTHONPATH=src python3 -m unittest discover -s tests -v
'''

CLAIMS_T8 = """# Claims under review (T8)

`src/reportcore/service.py` ships a `SavedReportsService` whose author states:

1. "Saved reports are permission safe: a report and its snapshot are readable only by
   members of the owning tenant, and confidential reports only by tenant admins. A
   caller cannot move a report into another tenant by supplying a tenant id."
2. "Revocation never changes the stored snapshot; the historical content hash is stable."
3. "`save_batch()` reports the truth about a batch: the count it returns is the count that
   was actually saved, and `status` is `complete` only when every item was saved."

The `DatasetRegistry` feature in the same module is believed correct and should not regress.

None of the three claims has been independently verified. Write automated acceptance tests
that would fail if a claim is untrue, and that pass on a correct implementation.
"""


def emit_reportcore(target: pathlib.Path, variant: str) -> None:
    if target.exists():
        shutil.rmtree(target)
    (target / "src" / "reportcore").mkdir(parents=True)
    (target / "tests").mkdir(parents=True)
    pkg = target / "src" / "reportcore"
    (pkg / "errors.py").write_text(ERRORS)
    (pkg / "models.py").write_text(MODELS)
    (pkg / "store.py").write_text(STORE)
    (pkg / "authz.py").write_text(AUTHZ)
    (pkg / "__init__.py").write_text(__init__)

    body = {"stub": SR_STUB, "defective": SR_DEFECTIVE, "correct": SR_CORRECT}[variant]
    service = SERVICE_COMMON + body
    if variant == "defective":
        # DEFECT D4: fail-open role gate (unknown role outranks every real role).
        service = service.replace(
            SERVICE_COMMON, SERVICE_COMMON.replace("from .models import CLASSIFICATIONS, User",
                                                   "from .models import CLASSIFICATIONS, User")
        )
    (pkg / "service.py").write_text(service)
    (target / "tests" / "test_smoke.py").write_text(
        VISIBLE_TESTS if variant == "stub" else VISIBLE_TESTS.split("    def test_viewer_cannot_save")[0]
        + '''
if __name__ == "__main__":
    unittest.main()
'''
    )
    (target / "run_checks.sh").write_text(RUN_CHECKS)
    (target / "README.md").write_text(README)
    if variant == "defective":
        (target / "CLAIMS.md").write_text(CLAIMS_T8)


def emit_authz_variants() -> None:
    """Defective authz for the T5/T8 trees: fail-open on roles the code does not know.

    Seeded as a plausible real-world bug ("only enforce roles we recognise"), not as an
    obvious placeholder, so a candidate has to reason about unknown/renamed roles.
    """
    bad = AUTHZ.replace(
        "from .models import User, role_level",
        "from .models import ROLE_LEVEL, User, role_level",
    ).replace(
        "    if role_level(actor.role) < role_level(minimum):\n        raise Forbidden",
        "    # DEFECT D4: only roles we recognise are enforced, so an unknown role fails open.\n"
        "    if actor.role in ROLE_LEVEL and role_level(actor.role) < role_level(minimum):\n"
        "        raise Forbidden",
    )
    path = FIX / "reportcore_t5" / "src" / "reportcore" / "authz.py"
    if path.exists():
        path.write_text(bad)
        (FIX / "reportcore_t8" / "src" / "reportcore" / "authz.py").write_text(bad)


def main() -> None:
    for d in (FIX, HID, REF):
        d.mkdir(parents=True, exist_ok=True)
    emit_reportcore(FIX / "reportcore_t3", "stub")
    emit_reportcore(FIX / "reportcore_t5", "defective")
    emit_reportcore(FIX / "reportcore_t8", "defective")
    emit_authz_variants()
    (REF / "service_correct.py").write_text(SERVICE_COMMON + SR_CORRECT)
    (REF / "authz_correct.py").write_text(AUTHZ)
    (REF / "README.md").write_text(
        "Reference (correct) implementations used to (a) prove each fixture is solvable and\n"
        "(b) serve as the mutation target for T8: a candidate test suite must FAIL on the\n"
        "defective tree and PASS when these two files replace src/reportcore/{service,authz}.py.\n"
    )
    print("wrote fixtures:", ", ".join(sorted(p.name for p in FIX.iterdir())))
    print("reference:", REF / "service_correct.py")


if __name__ == "__main__":
    main()
