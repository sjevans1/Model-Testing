"""Negative authorization and reporting tests for SavedReportsService."""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from reportcore import (  # noqa: E402
    Forbidden,
    NotFound,
    SavedReportsService,
    Store,
    User,
)
from reportcore.authz import may_read_classification  # noqa: E402


class TestSavedReportsAuthorization(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.store.seed_tenant("t1", "Tenant One")
        self.store.seed_tenant("t2", "Tenant Two")
        self.owner = User("u1", "t1", "owner@t1", "analyst")
        self.peer = User("u2", "t1", "peer@t1", "analyst")
        self.admin = User("u3", "t1", "admin@t1", "admin")
        self.foreign = User("u4", "t2", "foreign@t2", "admin")
        self.unknown = User("u5", "t1", "unknown@t1", "")
        self.unrecognized = User("u6", "t1", "unrecognized@t1", "superuser")
        self.viewer = User("u7", "t1", "viewer@t1", "viewer")
        self.service = SavedReportsService(self.store)

    def test_save_uses_authenticated_tenant_and_owner(self):
        report_id = self.service.save_report(
            self.owner,
            "Scoped",
            {"tenant_id": "t2", "owner_id": "u4", "rows": 2},
        )
        report = self.service.get_report(self.owner, report_id)
        self.assertEqual(report["tenant_id"], "t1")
        self.assertEqual(report["owner_id"], "u1")
        self.assertEqual(report["payload"]["tenant_id"], "t2")
        self.assertEqual(self.store.audit_rows(report_id)[0]["action"], "report.save")

    def test_foreign_get_and_revoke_are_indistinguishable_from_missing(self):
        report_id = self.service.save_report(self.owner, "Private", {"secret": 1})
        for method in (
            lambda: self.service.get_report(self.foreign, report_id),
            lambda: self.service.revoke_report(self.foreign, report_id),
            lambda: self.service.get_report(self.foreign, "missing"),
        ):
            with self.assertRaises(NotFound) as raised:
                method()
            self.assertEqual(str(raised.exception), "no such object")
        self.assertFalse(self.service.get_report(self.owner, report_id)["revoked"])
        self.assertEqual(
            [row["action"] for row in self.store.audit_rows(report_id)],
            ["report.save", "report.read"],
        )

    def test_list_is_tenant_scoped_and_reports_actual_revocation(self):
        own_id = self.service.save_report(self.owner, "Own", {})
        foreign_id = self.service.save_report(self.foreign, "Foreign", {})
        self.service.revoke_report(self.owner, own_id, "done")
        entries = self.service.list_reports(self.owner)
        self.assertEqual([entry["id"] for entry in entries], [own_id])
        self.assertTrue(entries[0]["revoked"])
        self.assertNotIn(foreign_id, {entry["id"] for entry in entries})

    def test_only_owner_or_tenant_admin_can_revoke(self):
        report_id = self.service.save_report(self.owner, "Owned", {})
        with self.assertRaises(Forbidden):
            self.service.revoke_report(self.peer, report_id)
        self.assertFalse(self.service.get_report(self.owner, report_id)["revoked"])
        self.service.revoke_report(self.admin, report_id, "admin action")
        self.assertTrue(self.service.get_report(self.owner, report_id)["revoked"])
        actions = [row["action"] for row in self.store.audit_rows(report_id)]
        self.assertEqual(actions.count("report.revoke"), 1)

    def test_confidential_reports_are_admin_only_and_reads_are_audited(self):
        with self.assertRaises(Forbidden):
            self.service.save_report(self.owner, "Classified", {}, "confidential")
        report_id = self.service.save_report(
            self.admin, "Classified", {"secret": True}, "confidential"
        )
        with self.assertRaises(Forbidden):
            self.service.get_report(self.owner, report_id)
        self.assertEqual(self.service.list_reports(self.owner), [])
        self.assertEqual(self.service.get_report(self.admin, report_id)["payload"], {"secret": True})
        actions = [row["action"] for row in self.store.audit_rows(report_id)]
        self.assertEqual(actions, ["report.save", "report.read"])
        self.assertTrue(may_read_classification(self.admin, "confidential"))
        self.assertFalse(may_read_classification(self.owner, "confidential"))

    def test_unknown_role_is_denied_at_every_service_entry_point(self):
        report_id = self.service.save_report(self.owner, "Known", {})
        with self.assertRaises(Forbidden):
            self.service.save_report(self.viewer, "No", {})
        for actor in (self.unknown, self.unrecognized):
            calls = (
                lambda: self.service.save_report(actor, "No", {}),
                lambda: self.service.get_report(actor, report_id),
                lambda: self.service.list_reports(actor),
                lambda: self.service.revoke_report(actor, report_id),
                lambda: self.service.save_batch(actor, []),
            )
            for call in calls:
                with self.subTest(actor=actor, call=call), self.assertRaises(Forbidden):
                    call()
            self.assertFalse(may_read_classification(actor, "internal"))
        self.assertFalse(self.service.get_report(self.owner, report_id)["revoked"])

    def test_batch_reports_successes_and_failures_truthfully(self):
        result = self.service.save_batch(
            self.owner,
            [
                {"name": "Saved", "payload": {"value": 1}},
                {"name": "", "payload": {}},
                "not-an-object",
            ],
        )
        self.assertEqual(result["applied"], 1)
        self.assertEqual(len(result["saved"]), 1)
        self.assertEqual(result["failed"], 2)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(self.store.audit_rows(result["saved"][0])), 1)

    def test_list_and_successful_read_are_audited(self):
        report_id = self.service.save_report(self.owner, "Audited", {})
        self.service.list_reports(self.owner)
        self.service.get_report(self.peer, report_id)
        actions = [row["action"] for row in self.store.audit_rows()]
        self.assertEqual(actions, ["report.save", "report.list", "report.read"])


if __name__ == "__main__":
    unittest.main()
