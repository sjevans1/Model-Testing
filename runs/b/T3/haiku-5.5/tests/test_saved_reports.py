"""Saved Reports behaviour tests."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from reportcore import (  # noqa: E402
    Conflict,
    Forbidden,
    NotFound,
    ReportCoreError,
    SavedReportsService,
    Store,
    User,
    ValidationError,
)


def make_store() -> Store:
    store = Store()
    store.seed_tenant("t1", "Tenant One")
    store.seed_tenant("t2", "Tenant Two")
    return store


def user(uid: str, tenant: str, role: str) -> User:
    return User(id=uid, tenant_id=tenant, email=f"{uid}@{tenant}", role=role)


class SavedReportsTest(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.svc = SavedReportsService(self.store)
        self.analyst = user("a1", "t1", "analyst")
        self.other_analyst = user("a2", "t1", "analyst")
        self.admin = user("adm1", "t1", "admin")
        self.viewer = user("v1", "t1", "viewer")
        self.foreign = user("f1", "t2", "admin")

    # save / snapshot
    def test_save_then_get_roundtrips_with_canonical_hash(self):
        payload = {"b": 2, "a": [1, 2]}
        rid = self.svc.save_report(self.analyst, "Q1", payload)
        got = self.svc.get_report(self.analyst, rid)
        self.assertEqual(got["payload"], payload)
        self.assertEqual(got["tenant_id"], "t1")
        self.assertEqual(got["owner_id"], "a1")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.assertEqual(got["content_hash"], hashlib.sha256(canonical.encode()).hexdigest())

    def test_snapshot_row_stored_as_canonical_json(self):
        rid = self.svc.save_report(self.analyst, "Q1", {"b": 2, "a": 1})
        row = self.store.fetchone("SELECT * FROM report_snapshots WHERE report_id = ?", (rid,))
        self.assertEqual(row["payload_json"], '{"a":1,"b":2}')

    def test_tenant_and_owner_come_from_actor_not_payload(self):
        payload = {"tenant_id": "t2", "owner_id": "evil", "classification": "confidential"}
        rid = self.svc.save_report(self.analyst, "Q", payload)
        row = self.store.fetchone("SELECT tenant_id, owner_id FROM reports WHERE id = ?", (rid,))
        self.assertEqual((row["tenant_id"], row["owner_id"]), ("t1", "a1"))
        # payload field named classification did not change the report classification
        got = self.svc.get_report(self.analyst, rid)
        self.assertEqual(got["classification"], "internal")

    def test_viewer_cannot_save(self):
        with self.assertRaises(Forbidden):
            self.svc.save_report(self.viewer, "Q", {"x": 1})

    def test_analyst_cannot_save_confidential(self):
        with self.assertRaises(Forbidden):
            self.svc.save_report(self.analyst, "Q", {"x": 1}, classification="confidential")

    def test_admin_can_save_confidential(self):
        rid = self.svc.save_report(self.admin, "Q", {"x": 1}, classification="confidential")
        self.assertEqual(self.svc.get_report(self.admin, rid)["classification"], "confidential")

    def test_validation_errors(self):
        for bad_name in ["", "   ", None, 5]:
            with self.assertRaises(ValidationError):
                self.svc.save_report(self.analyst, bad_name, {"x": 1})
        for bad_payload in [None, [1], "x"]:
            with self.assertRaises(ValidationError):
                self.svc.save_report(self.analyst, "Q", bad_payload)
        with self.assertRaises(ValidationError):
            self.svc.save_report(self.analyst, "Q", {"x": 1}, classification="secret")
        # validation happens before any write
        count = self.store.fetchone("SELECT COUNT(*) AS n FROM reports")["n"]
        self.assertEqual(count, 0)

    def test_save_writes_audit_row(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        actions = [r["action"] for r in self.store.audit_rows(rid)]
        self.assertEqual(actions, ["report.save"])

    # get / cross-tenant
    def test_get_unknown_id_is_not_found(self):
        with self.assertRaises(NotFound):
            self.svc.get_report(self.analyst, "does-not-exist")

    def test_cross_tenant_get_is_not_found_not_forbidden(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        with self.assertRaises(NotFound):
            self.svc.get_report(self.foreign, rid)

    def test_cross_tenant_error_identical_to_missing(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        with self.assertRaises(NotFound) as foreign_ctx:
            self.svc.get_report(self.foreign, rid)
        with self.assertRaises(NotFound) as missing_ctx:
            self.svc.get_report(self.foreign, "nope")
        self.assertEqual(str(foreign_ctx.exception), str(missing_ctx.exception))

    def test_confidential_hidden_from_analyst_on_get(self):
        rid = self.svc.save_report(self.admin, "Secret", {"x": 1}, classification="confidential")
        with self.assertRaises(Forbidden):
            self.svc.get_report(self.analyst, rid)

    def test_get_writes_read_audit_row(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        self.svc.get_report(self.analyst, rid)
        actions = [r["action"] for r in self.store.audit_rows(rid)]
        self.assertEqual(actions, ["report.save", "report.read"])

    def test_failed_get_writes_no_audit_row(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        with self.assertRaises(NotFound):
            self.svc.get_report(self.foreign, rid)
        self.assertEqual([r["action"] for r in self.store.audit_rows(rid)], ["report.save"])

    def test_get_detects_tampered_snapshot(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        self.store.execute(
            "UPDATE report_snapshots SET payload_json = ? WHERE report_id = ?",
            ('{"x":2}', rid),
        )
        self.store.commit()
        with self.assertRaises(ReportCoreError):
            self.svc.get_report(self.analyst, rid)

    # list
    def test_list_is_tenant_scoped_and_sorted(self):
        self.svc.save_report(self.analyst, "beta", {"x": 1})
        self.svc.save_report(self.analyst, "alpha", {"x": 1})
        self.svc.save_report(self.foreign, "foreign", {"x": 1})
        names = [r["name"] for r in self.svc.list_reports(self.analyst)]
        self.assertEqual(names, ["alpha", "beta"])
        self.assertEqual([r["name"] for r in self.svc.list_reports(self.foreign)], ["foreign"])

    def test_list_hides_confidential_from_non_admin(self):
        self.svc.save_report(self.analyst, "open", {"x": 1})
        self.svc.save_report(self.admin, "secret", {"x": 1}, classification="confidential")
        self.assertEqual([r["name"] for r in self.svc.list_reports(self.analyst)], ["open"])
        self.assertEqual(
            sorted(r["name"] for r in self.svc.list_reports(self.admin)), ["open", "secret"]
        )

    def test_list_writes_audit_row(self):
        self.svc.list_reports(self.analyst)
        self.assertEqual(self.store.audit_rows()[-1]["action"], "report.list")

    # revoke
    def test_owner_can_revoke_and_snapshot_is_preserved(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        before = dict(self.store.fetchone("SELECT * FROM report_snapshots WHERE report_id = ?", (rid,)))
        self.svc.revoke_report(self.analyst, rid, reason="stale")
        after = dict(self.store.fetchone("SELECT * FROM report_snapshots WHERE report_id = ?", (rid,)))
        self.assertEqual(before, after)
        row = self.store.fetchone("SELECT * FROM reports WHERE id = ?", (rid,))
        self.assertIsNotNone(row["revoked_at"])
        self.assertEqual((row["revoked_by"], row["revoke_reason"]), ("a1", "stale"))

    def test_revoked_report_not_retrievable_or_listed(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        self.svc.revoke_report(self.analyst, rid)
        with self.assertRaises(NotFound):
            self.svc.get_report(self.analyst, rid)
        self.assertEqual(self.svc.list_reports(self.analyst), [])

    def test_admin_can_revoke_others_report(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        self.svc.revoke_report(self.admin, rid)
        self.assertEqual(self.svc.list_reports(self.analyst), [])

    def test_non_owner_analyst_cannot_revoke(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        with self.assertRaises(Forbidden):
            self.svc.revoke_report(self.other_analyst, rid)
        self.assertIsNone(
            self.store.fetchone("SELECT revoked_at FROM reports WHERE id = ?", (rid,))["revoked_at"]
        )

    def test_viewer_cannot_revoke(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        with self.assertRaises(Forbidden):
            self.svc.revoke_report(self.viewer, rid)

    def test_cross_tenant_revoke_is_not_found(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        with self.assertRaises(NotFound):
            self.svc.revoke_report(self.foreign, rid)
        self.assertIsNone(
            self.store.fetchone("SELECT revoked_at FROM reports WHERE id = ?", (rid,))["revoked_at"]
        )

    def test_double_revoke_is_conflict(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        self.svc.revoke_report(self.analyst, rid)
        with self.assertRaises(Conflict):
            self.svc.revoke_report(self.analyst, rid)

    def test_revoke_writes_audit_row_with_reason(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        self.svc.revoke_report(self.analyst, rid, reason="superseded")
        row = self.store.audit_rows(rid)[-1]
        self.assertEqual((row["action"], row["detail"]), ("report.revoke", "superseded"))

    def test_revoke_validation(self):
        rid = self.svc.save_report(self.analyst, "Q", {"x": 1})
        with self.assertRaises(ValidationError):
            self.svc.revoke_report(self.analyst, rid, reason="x" * 501)
        with self.assertRaises(ValidationError):
            self.svc.revoke_report(self.analyst, "")
        with self.assertRaises(ValidationError):
            self.svc.revoke_report(self.analyst, rid, reason=None)

    def test_confidential_report_not_revocable_by_analyst_even_if_owner(self):
        # Analysts cannot create confidential reports, so this only guards a
        # confidential report later reached by a non-admin owner.
        rid = self.svc.save_report(self.admin, "Secret", {"x": 1}, classification="confidential")
        self.store.execute("UPDATE reports SET owner_id = 'a1' WHERE id = ?", (rid,))
        self.store.commit()
        with self.assertRaises(Forbidden):
            self.svc.revoke_report(self.analyst, rid)


if __name__ == "__main__":
    unittest.main()
