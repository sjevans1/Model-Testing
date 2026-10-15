"""Claim 1: permission safety of SavedReportsService (tenant scope, confidentiality, role gates, tenant injection)."""
from __future__ import annotations

import unittest

from reportcore import Forbidden, NotFound, User, ValidationError

from _support import ServiceTestCase, outcome


class TestNormalOperations(ServiceTestCase):
    def test_save_then_get_returns_payload_and_owning_tenant(self):
        rid = self.save(self.t1_analyst, "Q1 Revenue", {"rows": 3})
        got = self.reports.get_report(self.t1_analyst, rid)
        self.assertEqual(got["payload"], {"rows": 3})
        self.assertEqual(got["tenant_id"], "t1")
        self.assertEqual(got["owner_id"], self.t1_analyst.id)
        self.assertEqual(got["name"], "Q1 Revenue")
        self.assertFalse(got["revoked"])

    def test_same_tenant_viewer_can_read_internal_report(self):
        rid = self.save(self.t1_analyst, payload={"rows": 1})
        self.assertEqual(self.reports.get_report(self.t1_viewer, rid)["payload"], {"rows": 1})

    def test_list_contains_own_tenant_reports_only(self):
        self.save(self.t1_analyst, "T1 Report")
        self.save(self.t2_analyst, "T2 Report")
        self.assertEqual(self.list_names(self.t1_analyst), {"T1 Report"})
        self.assertEqual(self.list_names(self.t2_analyst), {"T2 Report"})


class TestInvalidInput(ServiceTestCase):
    def test_empty_name_is_rejected_and_nothing_is_stored(self):
        before = self.count_reports("t1")
        self.assertEqual(outcome(self.save, self.t1_analyst, "   ")[1], "ValidationError")
        self.assertEqual(self.count_reports("t1"), before)

    def test_non_object_payload_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.reports.save_report(self.t1_analyst, "X", ["not", "an", "object"])

    def test_unknown_classification_is_rejected(self):
        # Convention (README 1): validate input before touching the store. An unknown
        # label stored as-is would bypass the confidential gate entirely.
        before = self.count_reports("t1")
        with self.assertRaises(ValidationError):
            self.save(self.t1_analyst, "X", classification="Confidential ")
        self.assertEqual(self.count_reports("t1"), before)

    def test_missing_report_id_is_not_found(self):
        with self.assertRaises(NotFound):
            self.reports.get_report(self.t1_admin, "does-not-exist")


class TestUnauthorizedAccess(ServiceTestCase):
    def test_confidential_report_hidden_from_analyst_and_viewer(self):
        rid = self.save(self.t1_admin, "Board pack", classification="confidential")
        with self.assertRaises(Forbidden):
            self.reports.get_report(self.t1_analyst, rid)
        with self.assertRaises(Forbidden):
            self.reports.get_report(self.t1_viewer, rid)

    def test_confidential_report_readable_by_tenant_admin(self):
        rid = self.save(self.t1_admin, "Board pack", classification="confidential")
        self.assertEqual(self.reports.get_report(self.t1_admin, rid)["name"], "Board pack")

    def test_confidential_report_not_listed_for_analyst(self):
        self.save(self.t1_admin, "Board pack", classification="confidential")
        self.save(self.t1_analyst, "Team notes")
        self.assertEqual(self.list_names(self.t1_analyst), {"Team notes"})
        self.assertEqual(self.list_names(self.t1_admin), {"Board pack", "Team notes"})

    def test_revoked_report_is_not_listed_as_an_active_saved_report(self):
        rid = self.save(self.t1_analyst, "Retired")
        self.reports.revoke_report(self.t1_admin, rid, "retired")
        entries = [r for r in self.reports.list_reports(self.t1_analyst) if r["id"] == rid]
        # Either hiding the revoked report or listing it flagged as revoked is acceptable.
        # Listing it as active (revoked False) is not.
        self.assertTrue(all(e["revoked"] for e in entries), "a revoked report listed as active")
        self.assertTrue(self.reports.get_report(self.t1_analyst, rid)["revoked"])

    def test_viewer_cannot_save_a_report(self):
        # Convention (README 2) gates writes by role, as DatasetRegistry.save_dataset does.
        before = self.count_reports("t1")
        with self.assertRaises(Forbidden):
            self.save(self.t1_viewer, "Viewer write")
        self.assertEqual(self.count_reports("t1"), before)

    def test_viewer_cannot_revoke(self):
        rid = self.save(self.t1_analyst)
        with self.assertRaises(Forbidden):
            self.reports.revoke_report(self.t1_viewer, rid, "nope")
        self.assertFalse(self.reports.get_report(self.t1_analyst, rid)["revoked"])

    def test_unknown_role_cannot_revoke(self):
        # require_role() fails open for unrecognised roles (defect D4 in authz.py).
        rid = self.save(self.t1_analyst)
        rogue = User(id="ux", tenant_id="t1", email="x@t1", role="superuser")
        with self.assertRaises(Forbidden):
            self.reports.revoke_report(rogue, rid, "nope")
        self.assertFalse(self.reports.get_report(self.t1_analyst, rid)["revoked"])


class TestCrossTenantAccess(ServiceTestCase):
    def test_foreign_admin_cannot_read_report(self):
        rid = self.save(self.t1_analyst)
        with self.assertRaises(NotFound):
            self.reports.get_report(self.t2_admin, rid)

    def test_foreign_read_error_is_identical_to_missing_id(self):
        # Convention (README 3): a foreign object must be indistinguishable from a missing one.
        rid = self.save(self.t1_analyst)
        foreign = outcome(self.reports.get_report, self.t2_admin, rid)
        missing = outcome(self.reports.get_report, self.t2_admin, "does-not-exist")
        self.assertEqual(foreign, missing)

    def test_foreign_admin_cannot_read_confidential_report(self):
        rid = self.save(self.t1_admin, classification="confidential")
        with self.assertRaises(NotFound):
            self.reports.get_report(self.t2_admin, rid)

    def test_foreign_user_cannot_see_report_in_list(self):
        self.save(self.t1_analyst, "Secret T1 name")
        self.assertNotIn("Secret T1 name", self.list_names(self.t2_admin))

    def test_foreign_user_cannot_revoke_report(self):
        rid = self.save(self.t1_analyst)
        with self.assertRaises(NotFound):
            self.reports.revoke_report(self.t2_admin, rid, "cross-tenant")
        self.assertFalse(self.reports.get_report(self.t1_analyst, rid)["revoked"])

    def test_tenant_id_in_payload_cannot_move_report_into_another_tenant(self):
        # Claim 1: "a caller cannot move a report into another tenant by supplying a tenant id."
        rid = self.save(self.t1_analyst, payload={"rows": 1, "tenant_id": "t2"})
        row = self.report_row(rid)
        self.assertEqual(row["tenant_id"], "t1")
        self.assertEqual(self.count_reports("t2"), 0)
        self.assertEqual(self.reports.get_report(self.t1_analyst, rid)["tenant_id"], "t1")
        with self.assertRaises(NotFound):
            self.reports.get_report(self.t2_admin, rid)

class TestRoleChanges(ServiceTestCase):
    """The service trusts the User it is given (README 6). A role change is therefore
    expressed as a User object with the new role, and must take effect immediately."""

    def test_demoted_admin_loses_confidential_access(self):
        rid = self.save(self.t1_admin, classification="confidential")
        self.assertEqual(self.reports.get_report(self.t1_admin, rid)["name"], "Q1 Revenue")
        demoted = User(id=self.t1_admin.id, tenant_id="t1", email="d@t1", role="analyst")
        with self.assertRaises(Forbidden):
            self.reports.get_report(demoted, rid)
        self.assertNotIn("Q1 Revenue", self.list_names(demoted))

    def test_promoted_analyst_gains_confidential_access(self):
        rid = self.save(self.t1_admin, classification="confidential")
        promoted = User(id=self.t1_analyst.id, tenant_id="t1", email="a@t1", role="admin")
        self.assertEqual(self.reports.get_report(promoted, rid)["name"], "Q1 Revenue")

    def test_demoted_admin_cannot_revoke(self):
        rid = self.save(self.t1_analyst)
        demoted = User(id=self.t1_admin.id, tenant_id="t1", email="d@t1", role="viewer")
        with self.assertRaises(Forbidden):
            self.reports.revoke_report(demoted, rid, "demoted")
        self.assertFalse(self.reports.get_report(self.t1_analyst, rid)["revoked"])


class TestAuditTrail(ServiceTestCase):
    """Claimed in the SavedReportsService docstring; README convention 5."""

    def test_save_get_list_revoke_each_write_an_audit_row(self):
        rid = self.save(self.t1_analyst)
        self.reports.get_report(self.t1_analyst, rid)
        self.reports.list_reports(self.t1_analyst)
        self.reports.revoke_report(self.t1_admin, rid, "retired")
        actions = [r["action"] for r in self.store.audit_rows(rid)]
        self.assertEqual(actions, ["report.save", "report.read", "report.revoke"])
        self.assertIn("report.list", [r["action"] for r in self.store.audit_rows()])

    def test_audit_row_records_the_acting_user(self):
        rid = self.save(self.t1_analyst)
        row = self.store.audit_rows(rid)[0]
        self.assertEqual(row["actor_id"], self.t1_analyst.id)
        self.assertEqual(row["tenant_id"], "t1")


if __name__ == "__main__":
    unittest.main()
