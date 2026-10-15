"""Acceptance tests for the SavedReportsService contract in CLAIMS.md."""
from __future__ import annotations

import concurrent.futures
import pathlib
import tempfile
import threading
import unittest

from reportcore import (
    Forbidden,
    NotFound,
    SavedReportsService,
    Store,
    User,
    ValidationError,
    require_role,
)


class SavedReportsAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store()
        self.store.seed_tenant("t1", "Tenant One")
        self.store.seed_tenant("t2", "Tenant Two")
        self.service = SavedReportsService(self.store)
        self.admin = User("admin-1", "t1", "admin@t1", "admin")
        self.analyst = User("analyst-1", "t1", "analyst@t1", "analyst")
        self.viewer = User("viewer-1", "t1", "viewer@t1", "viewer")
        self.foreign_admin = User("admin-2", "t2", "admin@t2", "admin")

    def tearDown(self) -> None:
        self.store.conn.close()

    def save_internal(self, actor: User | None = None, name: str = "Quarterly") -> str:
        return self.service.save_report(actor or self.analyst, name, {"rows": [1, 2]})

    def test_analyst_save_round_trip_and_canonical_snapshot(self) -> None:
        report_id = self.service.save_report(
            self.analyst, "  Quarterly  ", {"z": 2, "a": 1}
        )
        got = self.service.get_report(self.viewer, report_id)
        self.assertEqual(got["id"], report_id)
        self.assertEqual(got["tenant_id"], "t1")
        self.assertEqual(got["owner_id"], self.analyst.id)
        self.assertEqual(got["name"], "Quarterly")
        self.assertEqual(got["payload"], {"a": 1, "z": 2})
        stored = self.store.fetchone(
            "SELECT payload_json, content_hash FROM report_snapshots WHERE report_id = ?",
            (report_id,),
        )
        self.assertEqual(stored["payload_json"], '{"a":1,"z":2}')
        self.assertEqual(got["content_hash"], stored["content_hash"])

    def test_invalid_name_payload_and_classification_are_rejected_without_writes(self) -> None:
        before = self.store.fetchone("SELECT COUNT(*) AS n FROM reports")["n"]
        invalid_calls = (
            (self.analyst, " \t ", {"ok": True}, "internal"),
            (self.analyst, "Valid", ["not", "an", "object"], "internal"),
            (self.admin, "Valid", {}, "top-secret"),
        )
        for actor, name, payload, classification in invalid_calls:
            with self.subTest(name=name, classification=classification):
                with self.assertRaises(ValidationError):
                    self.service.save_report(actor, name, payload, classification)
        after = self.store.fetchone("SELECT COUNT(*) AS n FROM reports")["n"]
        self.assertEqual(after, before)

    def test_unknown_roles_fail_closed_in_role_gate(self) -> None:
        unknown = User("mystery", "t1", "mystery@t1", "superuser")
        with self.assertRaises(Forbidden):
            require_role(unknown, "analyst")

    def test_viewer_and_unknown_role_cannot_create_reports(self) -> None:
        for actor in (
            self.viewer,
            User("mystery", "t1", "mystery@t1", "superuser"),
        ):
            with self.subTest(role=actor.role):
                with self.assertRaises(Forbidden):
                    self.service.save_report(actor, "Denied", {})
        self.assertEqual(
            self.store.fetchone("SELECT COUNT(*) AS n FROM reports")["n"], 0
        )

    def test_confidential_report_is_admin_only_for_get_and_list(self) -> None:
        internal_id = self.save_internal()
        confidential_id = self.service.save_report(
            self.admin, "Secret", {"secret": "value"}, "confidential"
        )
        self.assertEqual(self.service.get_report(self.admin, confidential_id)["payload"],
                         {"secret": "value"})
        with self.subTest("analyst confidential read"):
            with self.assertRaises(Forbidden):
                self.service.get_report(self.analyst, confidential_id)
        with self.subTest("viewer confidential read"):
            with self.assertRaises(Forbidden):
                self.service.get_report(self.viewer, confidential_id)
        analyst_ids = {entry["id"] for entry in self.service.list_reports(self.analyst)}
        with self.subTest("analyst confidential list"):
            self.assertEqual(analyst_ids, {internal_id})
        admin_ids = {entry["id"] for entry in self.service.list_reports(self.admin)}
        with self.subTest("admin list"):
            self.assertEqual(admin_ids, {internal_id, confidential_id})

    def test_payload_tenant_id_cannot_move_report_or_grant_foreign_access(self) -> None:
        report_id = self.service.save_report(
            self.analyst, "Spoofed", {"tenant_id": "t2", "data": 7}
        )
        own = self.service.get_report(self.analyst, report_id)
        with self.subTest("stored tenant follows actor"):
            self.assertEqual(own["tenant_id"], "t1")
        with self.subTest("foreign read is hidden"):
            with self.assertRaises(NotFound):
                self.service.get_report(self.foreign_admin, report_id)
        with self.subTest("foreign list is empty"):
            self.assertEqual(
                {entry["id"] for entry in self.service.list_reports(self.foreign_admin)}, set()
            )

    def test_foreign_list_and_reads_are_tenant_scoped(self) -> None:
        first = self.save_internal()
        second = self.service.save_report(self.foreign_admin, "Foreign", {"x": 2})
        with self.subTest("foreign read"):
            with self.assertRaises(NotFound):
                self.service.get_report(self.analyst, second)
        with self.subTest("missing read"):
            with self.assertRaises(NotFound):
                self.service.get_report(self.analyst, "does-not-exist")
        with self.subTest("tenant-scoped list"):
            self.assertEqual(
                {entry["id"] for entry in self.service.list_reports(self.analyst)}, {first}
            )

    def test_revoke_requires_admin_and_foreign_revoke_is_indistinguishable_from_missing(self) -> None:
        report_id = self.save_internal()
        with self.subTest("viewer revoke denied"):
            with self.assertRaises(Forbidden):
                self.service.revoke_report(self.viewer, report_id)
        with self.subTest("analyst revoke denied"):
            with self.assertRaises(Forbidden):
                self.service.revoke_report(self.analyst, report_id)
        with self.subTest("foreign revoke hidden"):
            with self.assertRaises(NotFound):
                self.service.revoke_report(self.foreign_admin, report_id)
        with self.subTest("denied revocations leave state untouched"):
            self.assertIsNone(
                self.store.fetchone(
                    "SELECT revoked_at FROM reports WHERE id = ?", (report_id,)
                )["revoked_at"]
            )
        self.service.revoke_report(self.admin, report_id, "retired")
        row = self.store.fetchone(
            "SELECT revoked_at, revoked_by, revoke_reason FROM reports WHERE id = ?",
            (report_id,),
        )
        self.assertIsNotNone(row["revoked_at"])
        self.assertEqual(row["revoked_by"], self.admin.id)
        self.assertEqual(row["revoke_reason"], "retired")

    def test_current_role_is_enforced_after_demotion_and_promotion(self) -> None:
        confidential_id = self.service.save_report(
            self.admin, "Sensitive", {"secret": 1}, "confidential"
        )
        demoted = User(self.admin.id, self.admin.tenant_id, self.admin.email, "analyst")
        with self.subTest("demoted confidential read denied"):
            with self.assertRaises(Forbidden):
                self.service.get_report(demoted, confidential_id)
        with self.subTest("demoted revoke denied"):
            with self.assertRaises(Forbidden):
                self.service.revoke_report(demoted, confidential_id)
        promoted = User(self.analyst.id, self.analyst.tenant_id, self.analyst.email, "admin")
        self.assertEqual(self.service.get_report(promoted, confidential_id)["payload"], {"secret": 1})
        self.service.revoke_report(promoted, confidential_id)

    def test_revocation_preserves_snapshot_bytes_and_hash(self) -> None:
        report_id = self.service.save_report(
            self.admin, "Immutable", {"nested": {"b": 2, "a": 1}}, "confidential"
        )
        before = self.store.fetchone(
            "SELECT payload_json, content_hash FROM report_snapshots WHERE report_id = ?",
            (report_id,),
        )
        self.service.revoke_report(self.admin, report_id, "superseded")
        after = self.store.fetchone(
            "SELECT payload_json, content_hash FROM report_snapshots WHERE report_id = ?",
            (report_id,),
        )
        self.assertEqual(tuple(after), tuple(before))
        got = self.service.get_report(self.admin, report_id)
        self.assertTrue(got["revoked"])
        self.assertEqual(got["content_hash"], before["content_hash"])
        self.assertEqual(got["payload"], {"nested": {"a": 1, "b": 2}})

    def test_revoked_reports_are_not_presented_as_saved_in_list(self) -> None:
        active_id = self.save_internal(name="Active")
        revoked_id = self.save_internal(name="Retired")
        self.service.revoke_report(self.admin, revoked_id)
        entries = self.service.list_reports(self.analyst)
        self.assertEqual({entry["id"] for entry in entries}, {active_id})

    def test_duplicate_batch_submissions_are_each_counted_and_persisted(self) -> None:
        duplicate = {"name": "Same", "payload": {"value": 1}}
        result = self.service.save_batch(self.analyst, [duplicate, duplicate.copy()])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["applied"], 2)
        self.assertEqual(len(result["saved"]), 2)
        self.assertEqual(len(set(result["saved"])), 2)
        rows = self.store.fetchall(
            "SELECT id FROM reports WHERE name = ? ORDER BY id", ("Same",)
        )
        self.assertEqual({row["id"] for row in rows}, set(result["saved"]))

    def test_batch_count_and_status_match_a_mixed_success_failure_batch(self) -> None:
        result = self.service.save_batch(
            self.analyst,
            [
                {"name": "Kept", "payload": {"n": 1}},
                {"name": "  ", "payload": {"n": 2}},
                {"name": "Also kept", "payload": {"n": 3}},
            ],
        )
        with self.subTest("reported applied count"):
            self.assertEqual(result["applied"], 2)
        with self.subTest("saved identifier count"):
            self.assertEqual(len(result["saved"]), 2)
        with self.subTest("partial status"):
            self.assertEqual(result["status"], "partial")
        with self.subTest("returned identifiers refer to saved reports"):
            for report_id in result["saved"]:
                self.assertEqual(
                    self.service.get_report(self.analyst, report_id)["tenant_id"], "t1"
                )
        with self.subTest("database count matches successful items"):
            self.assertEqual(
                self.store.fetchone("SELECT COUNT(*) AS n FROM reports")["n"], 2
            )

    def test_batch_with_no_successes_reports_failure_and_zero_applied(self) -> None:
        result = self.service.save_batch(
            self.analyst,
            [
                {"name": "", "payload": {"n": 1}},
                {"name": "   ", "payload": {"n": 2}},
            ],
        )
        with self.subTest("applied count"):
            self.assertEqual(result["applied"], 0)
        with self.subTest("saved IDs"):
            self.assertEqual(result["saved"], [])
        with self.subTest("failed status"):
            self.assertEqual(result["status"], "failed")
        with self.subTest("no persisted reports"):
            self.assertEqual(
                self.store.fetchone("SELECT COUNT(*) AS n FROM reports")["n"], 0
            )

    def test_concurrent_duplicate_saves_are_not_lost_or_corrupted(self) -> None:
        # Each worker owns its SQLite connection; a barrier makes writes contend.
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(pathlib.Path(directory) / "reports.sqlite")
            seed = Store(db_path)
            seed.seed_tenant("t1", "Tenant One")
            seed.commit()
            seed.conn.close()
            barrier = threading.Barrier(6)

            def save_one(index: int) -> str:
                store = Store(db_path)
                try:
                    barrier.wait(timeout=5)
                    service = SavedReportsService(store)
                    return service.save_report(
                        self.analyst, "Concurrent", {"submission": index}
                    )
                finally:
                    store.conn.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                report_ids = list(pool.map(save_one, range(6)))
            self.assertEqual(len(set(report_ids)), 6)
            check = Store(db_path)
            try:
                rows = check.fetchall(
                    "SELECT id FROM reports WHERE name = ?", ("Concurrent",)
                )
                snapshots = check.fetchall(
                    "SELECT payload_json, content_hash FROM report_snapshots"
                )
                self.assertEqual({row["id"] for row in rows}, set(report_ids))
                self.assertEqual(len(snapshots), 6)
                self.assertEqual(len({row["content_hash"] for row in snapshots}), 6)
            finally:
                check.conn.close()


if __name__ == "__main__":
    unittest.main()
