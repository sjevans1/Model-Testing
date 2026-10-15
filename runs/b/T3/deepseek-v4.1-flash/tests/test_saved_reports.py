"""Tests for SavedReportsService.

These exercise the behaviours the brief and README document: immutable snapshot
(canonical JSON + sha256), actor-derived tenant/owner, role gating, tenant scoping,
revocation that preserves the snapshot, audit rows, and the error types.
"""
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
    store.seed_user("u_alice", "t1", "alice@t1", "analyst")
    store.seed_user("u_ada", "t1", "ada@t1", "admin")
    store.seed_user("u_vera", "t1", "vera@t1", "viewer")
    store.seed_user("u_bob", "t2", "bob@t2", "analyst")
    store.seed_user("u_root2", "t2", "root@t2", "admin")
    return store


ALICE = User(id="u_alice", tenant_id="t1", email="alice@t1", role="analyst")
ADA = User(id="u_ada", tenant_id="t1", email="ada@t1", role="admin")
VERA = User(id="u_vera", tenant_id="t1", email="vera@t1", role="viewer")
BOB = User(id="u_bob", tenant_id="t2", email="bob@t2", role="analyst")
ROOT2 = User(id="u_root2", tenant_id="t2", email="root@t2", role="admin")
GHOST = User(id="u_ghost", tenant_id="t1", email="ghost@t1", role="ghost")

PAYLOAD = {"rows": 3, "title": "Q3 sales", "nested": {"b": 1, "a": [1, 2]}, "unicode": "café"}


class SavedReportsTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.store = make_store()
        self.svc = SavedReportsService(self.store)

    def snapshot_row(self, report_id: str):
        return self.store.fetchone(
            "SELECT * FROM report_snapshots WHERE report_id = ?", (report_id,)
        )

    def audit_actions(self) -> list[str]:
        return [r["action"] for r in self.store.audit_rows()]

    def audit_for(self, action: str) -> list:
        return [r for r in self.store.audit_rows() if r["action"] == action]


class TestSaveAndSnapshot(SavedReportsTestBase):
    def test_save_then_get_roundtrips(self):
        report_id = self.svc.save_report(ALICE, "Sales", PAYLOAD)
        got = self.svc.get_report(ALICE, report_id)
        self.assertEqual(got["payload"], PAYLOAD)
        self.assertEqual(got["name"], "Sales")
        self.assertEqual(got["classification"], "internal")
        self.assertEqual(got["status"], "active")

    def test_save_takes_tenant_and_owner_from_actor_not_payload(self):
        hostile = {
            "tenant_id": "t2",
            "owner_id": "u_bob",
            "rows": 1,
        }
        report_id = self.svc.save_report(ALICE, "Hostile", hostile)
        row = self.store.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))
        self.assertEqual(row["tenant_id"], "t1")
        self.assertEqual(row["owner_id"], "u_alice")
        # the payload is stored verbatim as caller-provided content
        self.assertEqual(self.svc.get_report(ALICE, report_id)["payload"], hostile)

    def test_snapshot_is_canonical_json_with_matching_sha256(self):
        report_id = self.svc.save_report(ALICE, "Canon", PAYLOAD)
        snap = self.snapshot_row(report_id)
        expected_blob = json.dumps(PAYLOAD, sort_keys=True, separators=(",", ":"), default=str)
        expected_digest = hashlib.sha256(expected_blob.encode("utf-8")).hexdigest()
        self.assertEqual(snap["payload_json"], expected_blob)
        self.assertEqual(snap["content_hash"], expected_digest)
        self.assertEqual(self.svc.get_report(ALICE, report_id)["content_hash"], expected_digest)

    def test_equal_payloads_hash_equal_and_both_snapshots_persist(self):
        a = self.svc.save_report(ALICE, "A", {"x": [1, {"y": 2}]})
        b = self.svc.save_report(ALICE, "B", {"x": [1, {"y": 2}]})
        self.assertNotEqual(a, b)
        self.assertEqual(
            self.snapshot_row(a)["content_hash"], self.snapshot_row(b)["content_hash"]
        )

    def test_name_is_stripped_and_ids_are_unique(self):
        first = self.svc.save_report(ALICE, "  Same  ", {"n": 1})
        second = self.svc.save_report(ALICE, "Same", {"n": 1})
        self.assertNotEqual(first, second)
        self.assertEqual(self.svc.get_report(ALICE, first)["name"], "Same")

    def test_get_returns_independent_payload_copies(self):
        report_id = self.svc.save_report(ALICE, "Copy", {"rows": [1]})
        got = self.svc.get_report(ALICE, report_id)
        got["payload"]["rows"].append(2)
        self.assertEqual(self.svc.get_report(ALICE, report_id)["payload"], {"rows": [1]})


class TestValidation(SavedReportsTestBase):
    def test_rejects_bad_name(self):
        for bad in ("", "   ", None, 7, ["x"]):
            with self.assertRaises(ValidationError):
                self.svc.save_report(ALICE, bad, {"rows": 1})
        self.assertEqual(self.store.fetchall("SELECT * FROM reports"), [])

    def test_rejects_non_object_payload(self):
        for bad in ([1, 2], "rows", 3, None):
            with self.assertRaises(ValidationError):
                self.svc.save_report(ALICE, "Bad", bad)
        self.assertEqual(self.store.fetchall("SELECT * FROM reports"), [])

    def test_rejects_unknown_classification(self):
        for bad in ("secret", "", None, 3, "Internal"):
            with self.assertRaises(ValidationError):
                self.svc.save_report(ALICE, "Bad", {"rows": 1}, classification=bad)

    def test_rejects_non_string_revoke_reason(self):
        report_id = self.svc.save_report(ALICE, "R", {"rows": 1})
        with self.assertRaises(ValidationError):
            self.svc.revoke_report(ALICE, report_id, reason=7)
        self.assertEqual(self.svc.get_report(ALICE, report_id)["status"], "active")

    def test_validation_precedes_authorization_like_dataset_registry(self):
        with self.assertRaises(ValidationError):
            self.svc.save_report(VERA, "", {"rows": 1})
        with self.assertRaises(Forbidden):
            self.svc.save_report(VERA, "Ok", {"rows": 1})


class TestAuthorization(SavedReportsTestBase):
    def test_viewer_cannot_save_or_revoke(self):
        with self.assertRaises(Forbidden):
            self.svc.save_report(VERA, "Nope", {"rows": 1})
        report_id = self.svc.save_report(ALICE, "Yes", {"rows": 1})
        with self.assertRaises(Forbidden):
            self.svc.revoke_report(VERA, report_id)
        self.assertEqual(self.svc.get_report(ALICE, report_id)["status"], "active")

    def test_unknown_role_fails_closed(self):
        with self.assertRaises(Forbidden):
            self.svc.save_report(GHOST, "Nope", {"rows": 1})
        report_id = self.svc.save_report(ALICE, "Yes", {"rows": 1})
        with self.assertRaises(Forbidden):
            self.svc.revoke_report(GHOST, report_id)

    def test_viewer_may_read_internal(self):
        report_id = self.svc.save_report(ALICE, "Shared", {"rows": 1})
        self.assertEqual(self.svc.get_report(VERA, report_id)["payload"], {"rows": 1})
        self.assertEqual([r["id"] for r in self.svc.list_reports(VERA)], [report_id])

    def test_confidential_save_requires_admin(self):
        with self.assertRaises(Forbidden):
            self.svc.save_report(ALICE, "Secret", {"rows": 1}, classification="confidential")
        self.assertEqual(self.store.fetchall("SELECT * FROM reports"), [])
        report_id = self.svc.save_report(ADA, "Secret", {"rows": 1}, classification="confidential")
        self.assertEqual(self.svc.get_report(ADA, report_id)["classification"], "confidential")

    def test_confidential_read_is_admin_only(self):
        report_id = self.svc.save_report(ADA, "Secret", {"rows": 1}, classification="confidential")
        with self.assertRaises(Forbidden):
            self.svc.get_report(ALICE, report_id)
        with self.assertRaises(Forbidden):
            self.svc.get_report(VERA, report_id)
        self.assertEqual(self.svc.list_reports(ALICE), [])
        self.assertEqual([r["id"] for r in self.svc.list_reports(ADA)], [report_id])

    def test_unknown_report_is_not_found(self):
        with self.assertRaises(NotFound):
            self.svc.get_report(ALICE, "does-not-exist")
        with self.assertRaises(NotFound):
            self.svc.revoke_report(ALICE, "does-not-exist")


class TestCrossTenant(SavedReportsTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.t1_report = self.svc.save_report(ALICE, "T1 report", {"rows": 1})
        self.t1_secret = self.svc.save_report(
            ADA, "T1 secret", {"rows": 2}, classification="confidential"
        )
        self.t2_report = self.svc.save_report(BOB, "T2 report", {"rows": 3})

    def test_cross_tenant_read_is_not_found(self):
        for rid in (self.t1_report, self.t1_secret):
            with self.assertRaises(NotFound):
                self.svc.get_report(BOB, rid)
        with self.assertRaises(NotFound):
            self.svc.get_report(ROOT2, self.t1_secret)

    def test_cross_tenant_write_is_not_found(self):
        for actor in (BOB, ROOT2):
            with self.assertRaises(NotFound):
                self.svc.revoke_report(actor, self.t1_report)
        self.assertEqual(self.svc.get_report(ALICE, self.t1_report)["status"], "active")

    def test_listing_is_tenant_scoped(self):
        self.assertEqual([r["id"] for r in self.svc.list_reports(ALICE)], [self.t1_report])
        self.assertEqual([r["id"] for r in self.svc.list_reports(BOB)], [self.t2_report])
        self.assertEqual(
            [r["id"] for r in self.svc.list_reports(ROOT2)], [self.t2_report]
        )

    def test_cross_tenant_error_does_not_disclose_existence(self):
        with self.assertRaises(NotFound) as owner_ctx:
            self.svc.get_report(ALICE, "no-such-id")
        with self.assertRaises(NotFound) as foreign_ctx:
            self.svc.get_report(BOB, self.t1_report)
        self.assertEqual(str(owner_ctx.exception), str(foreign_ctx.exception))

    def test_listing_rows_carry_the_tenant(self):
        rows = self.svc.list_reports(ALICE)
        self.assertEqual({r["tenant_id"] for r in rows}, {"t1"})
        self.assertEqual({r["owner_id"] for r in rows}, {"u_alice"})


class TestRevocation(SavedReportsTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.report_id = self.svc.save_report(ALICE, "Revokable", PAYLOAD)

    def test_revoke_flips_status_without_touching_the_snapshot(self):
        before = dict(self.snapshot_row(self.report_id))
        self.assertIsNone(self.svc.revoke_report(ALICE, self.report_id, reason="superseded"))
        after = dict(self.snapshot_row(self.report_id))
        self.assertEqual(before, after)

        got = self.svc.get_report(ALICE, self.report_id)
        self.assertEqual(got["status"], "revoked")
        self.assertIsNotNone(got["revoked_at"])
        self.assertEqual(got["revoked_by"], "u_alice")
        self.assertEqual(got["revoke_reason"], "superseded")
        self.assertEqual(got["content_hash"], before["content_hash"])
        self.assertEqual(got["payload"], PAYLOAD)

    def test_revoked_report_stays_readable_and_listed(self):
        self.svc.revoke_report(ALICE, self.report_id)
        self.assertEqual(self.svc.get_report(VERA, self.report_id)["payload"], PAYLOAD)
        listed = self.svc.list_reports(ALICE)
        self.assertEqual([r["id"] for r in listed], [self.report_id])
        self.assertEqual(listed[0]["status"], "revoked")

    def test_revoke_returns_none_and_default_reason_is_empty(self):
        self.assertIsNone(self.svc.revoke_report(ALICE, self.report_id))
        self.assertEqual(self.svc.get_report(ALICE, self.report_id)["revoke_reason"], "")

    def test_double_revoke_conflicts_and_leaves_state_alone(self):
        self.svc.revoke_report(ALICE, self.report_id, reason="first")
        first = dict(self.store.fetchone("SELECT * FROM reports WHERE id = ?", (self.report_id,)))
        with self.assertRaises(Conflict):
            self.svc.revoke_report(ADA, self.report_id, reason="second")
        second = dict(self.store.fetchone("SELECT * FROM reports WHERE id = ?", (self.report_id,)))
        self.assertEqual(first, second)

    def test_revoke_is_audited_with_reason(self):
        self.svc.revoke_report(ALICE, self.report_id, reason="superseded")
        rows = self.audit_for("report.revoke")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["actor_id"], "u_alice")
        self.assertEqual(row["tenant_id"], "t1")
        self.assertEqual(row["object_type"], "report")
        self.assertEqual(row["object_id"], self.report_id)
        self.assertEqual(row["detail"], "superseded")


class TestAudit(SavedReportsTestBase):
    def test_save_read_and_list_are_audited(self):
        report_id = self.svc.save_report(ALICE, "Audited", PAYLOAD)
        digest = self.svc.get_report(ALICE, report_id)["content_hash"]
        self.svc.list_reports(ALICE)

        saves = self.audit_for("report.save")
        self.assertEqual(len(saves), 1)
        self.assertEqual(saves[0]["actor_id"], "u_alice")
        self.assertEqual(saves[0]["tenant_id"], "t1")
        self.assertEqual(saves[0]["object_type"], "report")
        self.assertEqual(saves[0]["object_id"], report_id)
        self.assertEqual(saves[0]["detail"], digest)

        reads = self.audit_for("report.read")
        self.assertEqual([r["actor_id"] for r in reads], ["u_alice"])
        self.assertEqual(reads[0]["object_id"], report_id)

        lists = self.audit_for("report.list")
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0]["actor_id"], "u_alice")
        self.assertIsNone(lists[0]["object_id"])

    def test_no_audit_rows_are_written_for_rejected_requests(self):
        with self.assertRaises(Forbidden):
            self.svc.save_report(VERA, "Nope", {"rows": 1})
        with self.assertRaises(ValidationError):
            self.svc.save_report(ALICE, "", {"rows": 1})
        with self.assertRaises(NotFound):
            self.svc.get_report(BOB, "nope")
        self.assertEqual(self.store.audit_rows(), [])

    def test_failed_cross_tenant_read_is_not_audited_as_a_read(self):
        report_id = self.svc.save_report(ALICE, "T1", {"rows": 1})
        with self.assertRaises(NotFound):
            self.svc.get_report(BOB, report_id)
        self.assertEqual(self.audit_for("report.read"), [])


if __name__ == "__main__":
    unittest.main()
