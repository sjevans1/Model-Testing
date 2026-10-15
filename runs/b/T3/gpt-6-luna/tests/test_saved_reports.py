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


class TestSavedReportsService(unittest.TestCase):
    def setUp(self) -> None:
        self.store = make_store()
        self.service = SavedReportsService(self.store)
        self.owner = User("u1", "t1", "owner@example.test", "analyst")
        self.viewer = User("u2", "t1", "viewer@example.test", "viewer")
        self.other_tenant = User("u3", "t2", "other@example.test", "admin")
        self.admin = User("u4", "t1", "admin@example.test", "admin")

    def tearDown(self) -> None:
        self.store.conn.close()

    def test_snapshot_is_canonical_actor_owned_and_roundtrips(self) -> None:
        payload = {"z": [3, 2], "a": {"ok": True}, "tenant_id": "attacker", "owner_id": "attacker"}
        report_id = self.service.save_report(self.owner, "  Quarterly  ", payload)
        payload["z"].append(1)

        report = self.service.get_report(self.viewer, report_id)
        expected_blob = json.dumps(
            {"z": [3, 2], "a": {"ok": True}, "tenant_id": "attacker", "owner_id": "attacker"},
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(report["payload"]["z"], [3, 2])
        self.assertEqual(report["name"], "Quarterly")
        self.assertEqual(report["tenant_id"], "t1")
        self.assertEqual(report["owner_id"], "u1")
        self.assertEqual(report["content_hash"], hashlib.sha256(expected_blob.encode()).hexdigest())
        snapshot = self.store.fetchone(
            "SELECT payload_json, content_hash FROM report_snapshots WHERE report_id = ?", (report_id,)
        )
        self.assertEqual(snapshot["payload_json"], expected_blob)
        self.assertEqual(snapshot["content_hash"], report["content_hash"])

    def test_listing_is_tenant_scoped_and_hides_confidential_from_viewer(self) -> None:
        regular_id = self.service.save_report(self.owner, "Regular", {"x": 1})
        secret_id = self.service.save_report(self.admin, "Secret", {"x": 2}, "confidential")
        listed = self.service.list_reports(self.viewer)
        self.assertEqual([entry["id"] for entry in listed], [regular_id])
        self.assertNotIn(secret_id, [entry["id"] for entry in listed])
        self.assertEqual(self.service.list_reports(self.other_tenant), [])

    def test_cross_tenant_access_is_not_found_and_revoke_is_owner_or_admin_only(self) -> None:
        report_id = self.service.save_report(self.owner, "Owned", {"x": 1})
        with self.assertRaises(NotFound):
            self.service.get_report(self.other_tenant, report_id)
        with self.assertRaises(NotFound):
            self.service.revoke_report(self.other_tenant, report_id)
        with self.assertRaises(Forbidden):
            self.service.revoke_report(User("u5", "t1", "peer@example.test", "analyst"), report_id)

    def test_revoke_preserves_snapshot_and_is_audited(self) -> None:
        report_id = self.service.save_report(self.owner, "Owned", {"value": [1, 2]})
        before = dict(self.store.fetchone(
            "SELECT payload_json, content_hash, created_at FROM report_snapshots WHERE report_id = ?",
            (report_id,),
        ))
        self.assertEqual(self.service.get_report(self.viewer, report_id)["payload"], {"value": [1, 2]})
        self.service.revoke_report(self.owner, report_id, "superseded")
        after = dict(self.store.fetchone(
            "SELECT payload_json, content_hash, created_at FROM report_snapshots WHERE report_id = ?",
            (report_id,),
        ))
        self.assertEqual(after, before)
        report_row = self.store.fetchone("SELECT revoked_by, revoke_reason FROM reports WHERE id = ?", (report_id,))
        self.assertEqual((report_row["revoked_by"], report_row["revoke_reason"]), ("u1", "superseded"))
        self.assertEqual(self.service.list_reports(self.viewer), [])
        with self.assertRaises(Conflict):
            self.service.get_report(self.viewer, report_id)
        with self.assertRaises(Conflict):
            self.service.revoke_report(self.owner, report_id)
        actions = [row["action"] for row in self.store.audit_rows(report_id)]
        self.assertEqual(actions, ["report.save", "report.read", "report.revoke"])

    def test_validation_and_classification_authorization(self) -> None:
        with self.assertRaises(Forbidden):
            self.service.save_report(self.viewer, "No", {"x": 1})
        with self.assertRaises(Forbidden):
            self.service.save_report(self.owner, "Secret", {"x": 1}, "confidential")
        with self.assertRaises(ValidationError):
            self.service.save_report(self.owner, " ", {"x": 1})
        with self.assertRaises(ValidationError):
            self.service.save_report(self.owner, "Bad JSON", {"x": object()})
        with self.assertRaises(ValidationError):
            self.service.revoke_report(self.owner, "some-id", reason=object())

        secret_id = self.service.save_report(self.admin, "Secret", {"x": 1}, "confidential")
        with self.assertRaises(Forbidden):
            self.service.get_report(self.viewer, secret_id)
        self.assertEqual(self.service.get_report(self.admin, secret_id)["payload"], {"x": 1})


if __name__ == "__main__":
    unittest.main()
