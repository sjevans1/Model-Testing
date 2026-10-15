"""Shared fixtures for the SavedReportsService acceptance tests (stdlib only)."""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from reportcore import ReportCoreError, Store, User  # noqa: E402
from reportcore.service import DatasetRegistry, SavedReportsService  # noqa: E402


def outcome(fn, *args, **kwargs):
    """Run fn; return ("ok", value) or ("err", exception class name, message).

    Only ReportCoreError is captured. Any other exception is a real defect and
    propagates, so the test errors instead of quietly passing.
    """
    try:
        return ("ok", fn(*args, **kwargs))
    except ReportCoreError as exc:
        return ("err", type(exc).__name__, str(exc))


def item(name, payload=None, classification="internal"):
    """One batch item in the shape save_batch() documents."""
    entry = {"name": name, "payload": payload if payload is not None else {"rows": 1}}
    entry["classification"] = classification
    return entry


class ServiceTestCase(unittest.TestCase):
    """Two tenants, one user per role in each, and a fresh in-memory store per test."""

    def setUp(self):
        self.store = Store()
        self.store.seed_tenant("t1", "Tenant One")
        self.store.seed_tenant("t2", "Tenant Two")
        self.reports = SavedReportsService(self.store)
        self.datasets = DatasetRegistry(self.store)
        self.t1_viewer = User(id="u1v", tenant_id="t1", email="v@t1", role="viewer")
        self.t1_analyst = User(id="u1a", tenant_id="t1", email="a@t1", role="analyst")
        self.t1_admin = User(id="u1d", tenant_id="t1", email="d@t1", role="admin")
        self.t2_analyst = User(id="u2a", tenant_id="t2", email="a@t2", role="analyst")
        self.t2_admin = User(id="u2d", tenant_id="t2", email="d@t2", role="admin")

    def save(self, actor, name="Q1 Revenue", payload=None, classification="internal"):
        if payload is None:
            payload = {"rows": 3}
        return self.reports.save_report(actor, name, payload, classification)

    def report_row(self, report_id):
        return self.store.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))

    def snapshot_row(self, report_id):
        return self.store.fetchone(
            "SELECT * FROM report_snapshots WHERE report_id = ?", (report_id,)
        )

    def count_reports(self, tenant_id):
        row = self.store.fetchone(
            "SELECT COUNT(*) AS n FROM reports WHERE tenant_id = ?", (tenant_id,)
        )
        return row["n"]

    def list_names(self, actor):
        return {r["name"] for r in self.reports.list_reports(actor)}
