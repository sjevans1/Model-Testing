"""Negative authorization tests for SavedReportsService (tenant isolation, roles, audit)."""
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
    require_role,
    may_read_classification,
)


def make_env():
    store = Store()
    store.seed_tenant("t1", "Tenant One")
    store.seed_tenant("t2", "Tenant Two")
    svc = SavedReportsService(store)
    users = {
        "analyst1": User(id="a1", tenant_id="t1", email="a1@t1", role="analyst"),
        "admin1": User(id="d1", tenant_id="t1", email="d1@t1", role="admin"),
        "viewer1": User(id="v1", tenant_id="t1", email="v1@t1", role="viewer"),
        "analyst2": User(id="a2", tenant_id="t2", email="a2@t2", role="analyst"),
        "admin2": User(id="d2", tenant_id="t2", email="d2@t2", role="admin"),
    }
    return store, svc, users


class TestTenantIsolation(unittest.TestCase):
    def setUp(self):
        self.store, self.svc, self.u = make_env()
        self.report = self.svc.save_report(self.u["analyst1"], "R", {"k": 1})

    def test_foreign_tenant_read_is_not_found(self):
        with self.assertRaises(NotFound):
            self.svc.get_report(self.u["analyst2"], self.report)

    def test_foreign_tenant_admin_read_is_not_found(self):
        with self.assertRaises(NotFound):
            self.svc.get_report(self.u["admin2"], self.report)

    def test_missing_and_foreign_errors_are_identical(self):
        with self.assertRaises(NotFound) as foreign:
            self.svc.get_report(self.u["analyst2"], self.report)
        with self.assertRaises(NotFound) as missing:
            self.svc.get_report(self.u["analyst2"], "does-not-exist")
        self.assertEqual(str(foreign.exception), str(missing.exception))

    def test_foreign_tenant_revoke_is_not_found_and_does_not_mutate(self):
        with self.assertRaises(NotFound):
            self.svc.revoke_report(self.u["admin2"], self.report, "x")
        self.assertIsNone(
            self.store.fetchone("SELECT revoked_at FROM reports WHERE id=?", (self.report,))[0]
        )

    def test_list_excludes_other_tenants(self):
        self.svc.save_report(self.u["analyst2"], "Foreign", {"k": 9})
        names = [r["name"] for r in self.svc.list_reports(self.u["analyst1"])]
        self.assertEqual(names, ["R"])

    def test_payload_cannot_choose_tenant_or_owner(self):
        rid = self.svc.save_report(
            self.u["analyst1"], "Spoof", {"tenant_id": "t2", "owner_id": "d2"}
        )
        row = self.store.fetchone("SELECT tenant_id, owner_id FROM reports WHERE id=?", (rid,))
        self.assertEqual(row["tenant_id"], "t1")
        self.assertEqual(row["owner_id"], "a1")
        with self.assertRaises(NotFound):
            self.svc.get_report(self.u["admin2"], rid)


class TestRevocation(unittest.TestCase):
    def setUp(self):
        self.store, self.svc, self.u = make_env()
        self.report = self.svc.save_report(self.u["analyst1"], "R", {"k": 1})

    def test_non_owner_viewer_cannot_revoke(self):
        with self.assertRaises(Forbidden):
            self.svc.revoke_report(self.u["viewer1"], self.report, "x")

    def test_non_owner_analyst_cannot_revoke(self):
        other = User(id="a9", tenant_id="t1", email="a9@t1", role="analyst")
        with self.assertRaises(Forbidden):
            self.svc.revoke_report(other, self.report, "x")

    def test_tenant_admin_can_revoke(self):
        self.svc.revoke_report(self.u["admin1"], self.report, "policy")
        row = self.store.fetchone("SELECT revoked_at, revoked_by FROM reports WHERE id=?", (self.report,))
        self.assertIsNotNone(row["revoked_at"])
        self.assertEqual(row["revoked_by"], "d1")

    def test_owner_can_revoke(self):
        self.svc.revoke_report(self.u["analyst1"], self.report, "mine")
        row = self.store.fetchone("SELECT revoked_at FROM reports WHERE id=?", (self.report,))
        self.assertIsNotNone(row["revoked_at"])

    def test_revoked_report_is_hidden_from_list(self):
        self.svc.revoke_report(self.u["admin1"], self.report, "policy")
        self.assertEqual(self.svc.list_reports(self.u["analyst1"]), [])

    def test_revocation_does_not_change_snapshot_hash(self):
        before = self.svc.get_report(self.u["admin1"], self.report)["content_hash"]
        self.svc.revoke_report(self.u["admin1"], self.report, "policy")
        after = self.svc.get_report(self.u["admin1"], self.report)
        self.assertEqual(before, after["content_hash"])
        self.assertTrue(after["revoked"])


class TestClassification(unittest.TestCase):
    def setUp(self):
        self.store, self.svc, self.u = make_env()
        self.conf = self.svc.save_report(
            self.u["admin1"], "Secret", {"k": "s"}, "confidential"
        )
        self.internal = self.svc.save_report(self.u["analyst1"], "Open", {"k": "o"})

    def test_viewer_cannot_read_confidential(self):
        with self.assertRaises(Forbidden):
            self.svc.get_report(self.u["viewer1"], self.conf)

    def test_analyst_cannot_read_confidential(self):
        with self.assertRaises(Forbidden):
            self.svc.get_report(self.u["analyst1"], self.conf)

    def test_admin_can_read_confidential(self):
        self.assertEqual(self.svc.get_report(self.u["admin1"], self.conf)["payload"], {"k": "s"})

    def test_viewer_can_read_internal(self):
        self.assertEqual(self.svc.get_report(self.u["viewer1"], self.internal)["name"], "Open")

    def test_list_hides_confidential_from_non_admin(self):
        names = [r["name"] for r in self.svc.list_reports(self.u["analyst1"])]
        self.assertEqual(names, ["Open"])
        names = [r["name"] for r in self.svc.list_reports(self.u["admin1"])]
        self.assertEqual(names, ["Open", "Secret"])

    def test_analyst_cannot_create_confidential(self):
        with self.assertRaises(Forbidden):
            self.svc.save_report(self.u["analyst1"], "X", {}, "confidential")

    def test_viewer_cannot_save_report(self):
        with self.assertRaises(Forbidden):
            self.svc.save_report(self.u["viewer1"], "X", {})


class TestFailClosedRoles(unittest.TestCase):
    def setUp(self):
        self.store, self.svc, self.u = make_env()
        self.report = self.svc.save_report(self.u["analyst1"], "R", {"k": 1})
        self.conf = self.svc.save_report(self.u["admin1"], "S", {"k": 2}, "confidential")
        self.unknown = [
            User(id="x1", tenant_id="t1", email="x@t1", role="superuser"),
            User(id="x2", tenant_id="t1", email="y@t1", role=""),
            User(id="x3", tenant_id="t1", email="z@t1", role="ADMIN"),
        ]

    def test_require_role_denies_unknown_roles(self):
        for actor in self.unknown:
            with self.subTest(role=actor.role):
                with self.assertRaises(Forbidden):
                    require_role(actor, "viewer")

    def test_classification_predicate_denies_unknown_roles(self):
        for actor in self.unknown:
            with self.subTest(role=actor.role):
                self.assertFalse(may_read_classification(actor, "internal"))
                self.assertFalse(may_read_classification(actor, "confidential"))

    def test_unknown_role_cannot_read_report(self):
        for actor in self.unknown:
            with self.subTest(role=actor.role):
                with self.assertRaises(Forbidden):
                    self.svc.get_report(actor, self.report)

    def test_unknown_role_cannot_save_or_revoke(self):
        for actor in self.unknown:
            with self.subTest(role=actor.role):
                with self.assertRaises(Forbidden):
                    self.svc.save_report(actor, "X", {})
                with self.assertRaises(Forbidden):
                    self.svc.revoke_report(actor, self.report, "x")

    def test_unknown_role_list_is_empty(self):
        for actor in self.unknown:
            with self.subTest(role=actor.role):
                self.assertEqual(self.svc.list_reports(actor), [])

    def test_unknown_classification_is_not_readable(self):
        self.assertFalse(may_read_classification(self.u["admin1"], "top-secret"))


class TestBatch(unittest.TestCase):
    def setUp(self):
        self.store, self.svc, self.u = make_env()

    def count_reports(self):
        return self.store.fetchone("SELECT COUNT(*) FROM reports")[0]

    def test_all_good_is_complete(self):
        result = self.svc.save_batch(
            self.u["analyst1"], [{"name": "a", "payload": {}}, {"name": "b", "payload": {}}]
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["applied"], 2)
        self.assertEqual(len(result["saved"]), 2)
        self.assertEqual(self.count_reports(), 2)

    def test_partial_failure_is_reported_truthfully(self):
        result = self.svc.save_batch(
            self.u["analyst1"],
            [
                {"name": "ok", "payload": {}},
                {"name": "", "payload": {}},
                {"name": "secret", "payload": {}, "classification": "confidential"},
            ],
        )
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["applied"], 1)
        self.assertEqual(len(result["saved"]), 1)
        self.assertEqual(result["requested"], 3)
        self.assertEqual([f["index"] for f in result["failed"]], [1, 2])
        self.assertEqual(self.count_reports(), 1)

    def test_total_failure_is_failed_not_complete(self):
        result = self.svc.save_batch(self.u["viewer1"], [{"name": "a", "payload": {}}])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["applied"], 0)
        self.assertEqual(result["saved"], [])
        self.assertEqual(self.count_reports(), 0)

    def test_applied_matches_actual_rows(self):
        self.svc.save_batch(
            self.u["analyst1"],
            [{"name": "a", "payload": {}}, {"name": None, "payload": {}}, {"name": "c"}],
        )
        self.assertEqual(self.count_reports(), 2)


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.store, self.svc, self.u = make_env()

    def actions_for(self, object_id):
        return [r["action"] for r in self.store.audit_rows(object_id)]

    def test_save_is_audited(self):
        rid = self.svc.save_report(self.u["analyst1"], "R", {})
        self.assertIn("report.save", self.actions_for(rid))

    def test_read_is_audited(self):
        rid = self.svc.save_report(self.u["analyst1"], "R", {})
        self.svc.get_report(self.u["analyst1"], rid)
        self.assertIn("report.read", self.actions_for(rid))

    def test_revoke_is_audited(self):
        rid = self.svc.save_report(self.u["analyst1"], "R", {})
        self.svc.revoke_report(self.u["analyst1"], rid, "x")
        self.assertIn("report.revoke", self.actions_for(rid))

    def test_list_is_audited(self):
        self.svc.list_reports(self.u["analyst1"])
        actions = [r["action"] for r in self.store.audit_rows()]
        self.assertIn("report.list", actions)


if __name__ == "__main__":
    unittest.main()
