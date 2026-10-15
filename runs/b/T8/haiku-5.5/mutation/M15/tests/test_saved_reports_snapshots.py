"""Claim 2: revocation never changes the stored snapshot; the historical content hash is stable.

Also covers snapshot integrity (stored hash matches stored payload) and duplicate submissions,
since duplicates must not be able to overwrite or re-hash an earlier snapshot.
"""
from __future__ import annotations

import hashlib
import json
import unittest

from reportcore import Forbidden, NotFound

from _support import ServiceTestCase


def _digest_of(payload):
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class TestRevocationKeepsSnapshot(ServiceTestCase):
    def test_revoke_leaves_snapshot_row_byte_identical(self):
        rid = self.save(self.t1_analyst, payload={"rows": 3, "total": 42.5})
        before = tuple(self.snapshot_row(rid))
        self.reports.revoke_report(self.t1_admin, rid, "superseded")
        self.assertEqual(tuple(self.snapshot_row(rid)), before)

    def test_content_hash_and_payload_are_stable_across_revocation(self):
        payload = {"rows": 3, "total": 42.5, "region": "EU"}
        rid = self.save(self.t1_analyst, payload=payload)
        before = self.reports.get_report(self.t1_analyst, rid)
        self.reports.revoke_report(self.t1_admin, rid, "superseded")
        after = self.reports.get_report(self.t1_admin, rid)
        self.assertEqual(after["content_hash"], before["content_hash"])
        self.assertEqual(after["payload"], payload)
        self.assertTrue(after["revoked"])

    def test_stored_hash_matches_canonical_payload_before_and_after_revoke(self):
        payload = {"b": 2, "a": [1, 2]}
        rid = self.save(self.t1_analyst, payload=payload)
        expected = _digest_of(payload)
        self.assertEqual(self.snapshot_row(rid)["content_hash"], expected)
        self.reports.revoke_report(self.t1_admin, rid, "x")
        self.assertEqual(self.snapshot_row(rid)["content_hash"], expected)

    def test_revoke_only_changes_report_status_columns(self):
        rid = self.save(self.t1_analyst, "Original name", classification="internal")
        before = dict(self.report_row(rid))
        self.reports.revoke_report(self.t1_admin, rid, "superseded")
        after = dict(self.report_row(rid))
        for column in ("id", "tenant_id", "owner_id", "name", "classification", "created_at"):
            self.assertEqual(after[column], before[column], column)
        self.assertIsNotNone(after["revoked_at"])
        self.assertEqual(after["revoked_by"], self.t1_admin.id)
        self.assertEqual(after["revoke_reason"], "superseded")

    def test_revoking_twice_keeps_snapshot_and_revoked_state(self):
        rid = self.save(self.t1_analyst, payload={"rows": 9})
        before = tuple(self.snapshot_row(rid))
        self.reports.revoke_report(self.t1_admin, rid, "first")
        self.reports.revoke_report(self.t1_admin, rid, "second")
        self.assertEqual(tuple(self.snapshot_row(rid)), before)
        self.assertTrue(self.reports.get_report(self.t1_admin, rid)["revoked"])

    def test_revoked_report_content_still_readable_by_owner_tenant(self):
        payload = {"rows": 5}
        rid = self.save(self.t1_analyst, payload=payload)
        self.reports.revoke_report(self.t1_admin, rid, "x")
        self.assertEqual(self.reports.get_report(self.t1_analyst, rid)["payload"], payload)


class TestSnapshotIntegrity(ServiceTestCase):
    def test_hash_is_canonical_so_key_order_does_not_change_it(self):
        a = self.save(self.t1_analyst, "A", payload={"x": 1, "y": 2})
        b = self.save(self.t1_analyst, "B", payload={"y": 2, "x": 1})
        self.assertEqual(
            self.snapshot_row(a)["content_hash"], self.snapshot_row(b)["content_hash"]
        )

    def test_different_payloads_produce_different_hashes(self):
        a = self.save(self.t1_analyst, payload={"rows": 1})
        b = self.save(self.t1_analyst, payload={"rows": 2})
        self.assertNotEqual(
            self.snapshot_row(a)["content_hash"], self.snapshot_row(b)["content_hash"]
        )

    def test_returned_hash_matches_recomputed_hash_of_returned_payload(self):
        rid = self.save(self.t1_analyst, payload={"k": ["v", 1, None]})
        got = self.reports.get_report(self.t1_analyst, rid)
        self.assertEqual(got["content_hash"], _digest_of(got["payload"]))


class TestDuplicateSubmissions(ServiceTestCase):
    def test_identical_resubmission_leaves_first_snapshot_intact(self):
        payload = {"rows": 3}
        first = self.save(self.t1_analyst, "Q1", payload=payload)
        before = tuple(self.snapshot_row(first))
        self.save(self.t1_analyst, "Q1", payload=payload)
        self.assertEqual(tuple(self.snapshot_row(first)), before)
        self.assertEqual(self.reports.get_report(self.t1_analyst, first)["payload"], payload)

    def test_resubmission_with_different_payload_does_not_rewrite_first_snapshot(self):
        first = self.save(self.t1_analyst, "Q1", payload={"rows": 3})
        original_hash = self.snapshot_row(first)["content_hash"]
        self.save(self.t1_analyst, "Q1", payload={"rows": 999})
        got = self.reports.get_report(self.t1_analyst, first)
        self.assertEqual(got["payload"], {"rows": 3})
        self.assertEqual(got["content_hash"], original_hash)


if __name__ == "__main__":
    unittest.main()
