"""Shared fixtures and helpers for the SavedReports acceptance suite (T8).

The helpers are deliberately thin: everything they do is something a caller of the
public API could do too (plus raw sqlite reads through ``Store``, which is the documented
persistence surface, so that "the snapshot on disk is unchanged" can be checked without
trusting the service's own return value).

No third-party packages, no network, no clock or randomness assumptions.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reportcore import ReportCoreError, SavedReportsService, Store, User  # noqa: E402

TENANTS = {"t1": "Tenant One", "t2": "Tenant Two"}


# --------------------------------------------------------------------------- fixtures

def make_store(path: str = ":memory:") -> Store:
    store = Store(path)
    for tenant_id, name in TENANTS.items():
        store.seed_tenant(tenant_id, name)
    return store


def user(user_id: str, tenant_id: str = "t1", role: str = "analyst") -> User:
    return User(id=user_id, tenant_id=tenant_id, email=f"{user_id}@{tenant_id}.example", role=role)


def admin(tenant_id: str = "t1") -> User:
    return user(f"{tenant_id}-admin", tenant_id, "admin")


def analyst(tenant_id: str = "t1") -> User:
    return user(f"{tenant_id}-analyst", tenant_id, "analyst")


def viewer(tenant_id: str = "t1") -> User:
    return user(f"{tenant_id}-viewer", tenant_id, "viewer")


# ------------------------------------------------------------------- content hashing

def canonical_json(payload) -> str:
    """The canonical form the package documents: sorted keys, no insignificant spaces."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(payload) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


# --------------------------------------------------------------- raw persistence reads

def report_row(store: Store, report_id):
    return store.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))


def snapshot_row(store: Store, report_id):
    return store.fetchone("SELECT * FROM report_snapshots WHERE report_id = ?", (report_id,))


def snapshot_fingerprint(store: Store, report_id):
    """The bytes of the stored snapshot, or None. Two equal fingerprints == identical row."""
    row = snapshot_row(store, report_id)
    if row is None:
        return None
    return (row["payload_json"], row["content_hash"])


def count(store: Store, table: str) -> int:
    return store.fetchone(f"SELECT COUNT(*) AS n FROM {table}")["n"]


# ------------------------------------------------------------- "what can this actor see"

def read_surface(svc: SavedReportsService, actor: User, report_id: str) -> list:
    """Call every public read entry point of the report service.

    Returns ``(label, "returned", value)`` or ``(label, "raised", ExceptionName)``.
    Any non-``ReportCoreError`` exception is a bug and is allowed to propagate.
    """
    calls = (
        ("get_report", lambda: svc.get_report(actor, report_id)),
        ("list_reports", lambda: svc.list_reports(actor)),
    )
    outcomes = []
    for label, call in calls:
        try:
            outcomes.append((label, "returned", call()))
        except ReportCoreError as exc:
            outcomes.append((label, "raised", type(exc).__name__))
    return outcomes


def surfaces(outcomes: list, report_id: str) -> list:
    """Which entry points handed *report_id* back to the caller."""
    return [label for label, kind, value in outcomes if kind == "returned" and report_id in repr(value)]


# -------------------------------------------------------------------------- test base

class SavedReportsCase(unittest.TestCase):
    """Fresh in-memory store, service and one actor per (tenant, role) for each test."""

    def setUp(self):
        self.store = make_store()
        self.svc = SavedReportsService(self.store)
        self.t1_admin = admin("t1")
        self.t1_analyst = analyst("t1")
        self.t1_viewer = viewer("t1")
        self.t2_admin = admin("t2")
        self.t2_analyst = analyst("t2")
        self.t2_viewer = viewer("t2")

    def save(self, actor: User, name: str = "Report", payload=None, classification: str = "internal") -> str:
        if payload is None:
            payload = {"rows": 1}
        return self.svc.save_report(actor, name, payload, classification)
