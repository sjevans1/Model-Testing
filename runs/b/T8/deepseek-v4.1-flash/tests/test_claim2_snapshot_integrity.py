"""CLAIM 2 (snapshot immutability under revocation).

CLAIMS.md: "Revocation never changes the stored snapshot; the historical content hash is
stable."

Detection logic: the snapshot is compared *byte for byte* at the persistence layer
(``report_snapshots.payload_json`` / ``content_hash``) before and after revocation, and the
service's own view must agree with those bytes.  A rewrite, a delete, a re-hash or a
re-canonicalisation of the stored snapshot all fail these tests.

Revocation is also a privileged mutation, so the tenant scope and the role gate on it are
covered here (CLAIM 1's "readable only by members of the owning tenant" would otherwise be
undone by anyone being able to revoke a foreign report).
"""
from __future__ import annotations

import json

from reportcore import Forbidden, NotFound, ReportCoreError

from support import (
    SavedReportsCase,
    canonical_json,
    content_hash,
    count,
    snapshot_fingerprint,
    snapshot_row,
)


class Claim2SnapshotIntegrity(SavedReportsCase):

    # -------------------------------------------------- what "the stored snapshot" means

    def test_save_stores_canonical_json_and_matching_sha256(self):
        payload = {"rows": 3, "cols": 2, "title": "Q3"}
        report_id = self.save(self.t1_analyst, "Q3", payload)

        row = snapshot_row(self.store, report_id)
        self.assertIsNotNone(row, "a saved report must have a stored snapshot")
        self.assertEqual(row["payload_json"], canonical_json(payload))
        self.assertEqual(row["content_hash"], content_hash(payload))
        self.assertEqual(
            self.svc.get_report(self.t1_analyst, report_id)["content_hash"], content_hash(payload)
        )

    def test_equal_payloads_hash_equal_whatever_the_key_order(self):
        first = self.save(self.t1_analyst, "A", {"rows": 3, "cols": 2})
        second = self.save(self.t1_analyst, "B", {"cols": 2, "rows": 3})

        hash_a = self.svc.get_report(self.t1_analyst, first)["content_hash"]
        hash_b = self.svc.get_report(self.t1_analyst, second)["content_hash"]
        self.assertEqual(hash_a, hash_b, "the digest must be over canonical JSON, not raw order")
        self.assertEqual(hash_a, content_hash({"rows": 3, "cols": 2}))

    # ------------------------------------------------------- revocation preserves content

    def test_revoke_leaves_the_stored_snapshot_byte_identical(self):
        payload = {"rows": 1, "note": "historical"}
        report_id = self.save(self.t1_analyst, "R", payload)
        stored_before = snapshot_fingerprint(self.store, report_id)
        view_before = self.svc.get_report(self.t1_analyst, report_id)

        self.svc.revoke_report(self.t1_admin, report_id, "policy")

        self.assertEqual(snapshot_fingerprint(self.store, report_id), stored_before)
        view_after = self.svc.get_report(self.t1_analyst, report_id)
        self.assertEqual(view_after["payload"], view_before["payload"])
        self.assertEqual(view_after["content_hash"], view_before["content_hash"])
        self.assertEqual(view_after["content_hash"], content_hash(payload))
        self.assertTrue(view_after["revoked"], "the revoked flag must reflect the revocation")

    def test_revoke_neither_deletes_nor_duplicates_the_snapshot(self):
        report_id = self.save(self.t1_analyst, "R")
        self.svc.revoke_report(self.t1_admin, report_id)
        self.assertEqual(count(self.store, "report_snapshots"), 1)
        self.assertEqual(count(self.store, "reports"), 1)
        self.assertIsNotNone(snapshot_row(self.store, report_id))

    def test_revoked_report_is_still_readable_to_the_owning_tenant(self):
        report_id = self.save(self.t1_analyst, "R", {"rows": 7})
        self.svc.revoke_report(self.t1_admin, report_id)
        got = self.svc.get_report(self.t1_viewer, report_id)
        self.assertEqual(got["payload"], {"rows": 7})
        self.assertTrue(got["revoked"])

    def test_history_is_stable_across_repeated_reads_after_revocation(self):
        report_id = self.save(self.t1_analyst, "R", {"rows": 7})
        self.svc.revoke_report(self.t1_admin, report_id)
        hashes = {self.svc.get_report(self.t1_analyst, report_id)["content_hash"] for _ in range(5)}
        self.assertEqual(len(hashes), 1, f"content hash drifted across reads: {hashes}")
        self.assertEqual(hashes.pop(), content_hash({"rows": 7}))

    def test_repeated_revocation_does_not_mutate_the_snapshot(self):
        """A conflicting/duplicate revocation must not rewrite or lose the historical content.

        The contract does not say whether a second revocation is rejected or accepted, so
        both outcomes are allowed; what is *not* allowed is a changed snapshot, a lost
        revocation or a duplicated snapshot row.
        """
        report_id = self.save(self.t1_analyst, "R", {"rows": 7})
        self.svc.revoke_report(self.t1_admin, report_id, "first")
        stored = snapshot_fingerprint(self.store, report_id)

        try:
            self.svc.revoke_report(self.t1_admin, report_id, "second")
        except ReportCoreError:
            pass  # rejecting a duplicate revocation is fine

        self.assertEqual(snapshot_fingerprint(self.store, report_id), stored)
        self.assertTrue(self.svc.get_report(self.t1_analyst, report_id)["revoked"])
        self.assertEqual(count(self.store, "report_snapshots"), 1)

    def test_snapshot_is_not_aliased_between_two_reports_with_equal_content(self):
        """Revoking one of two identical reports must not touch the other (conflicting update)."""
        payload = {"rows": 3, "cols": 2}
        first = self.save(self.t1_analyst, "A", payload)
        second = self.save(self.t1_analyst, "B", payload)
        self.assertNotEqual(first, second)

        self.svc.revoke_report(self.t1_admin, first)

        self.assertTrue(self.svc.get_report(self.t1_analyst, first)["revoked"])
        other = self.svc.get_report(self.t1_analyst, second)
        self.assertFalse(other["revoked"], "revoking one report revoked an unrelated one")
        self.assertEqual(other["content_hash"], content_hash(payload))
        self.assertEqual(count(self.store, "report_snapshots"), 2)

    # --------------------------------------------------------- revocation is privileged

    def test_revoke_requires_an_admin_role(self):
        report_id = self.save(self.t1_analyst, "R")
        stored = snapshot_fingerprint(self.store, report_id)

        for actor in (self.t1_viewer, self.t1_analyst):
            with self.assertRaises(Forbidden):
                self.svc.revoke_report(actor, report_id, "nope")

        self.assertEqual(snapshot_fingerprint(self.store, report_id), stored)
        self.assertFalse(
            self.svc.get_report(self.t1_analyst, report_id)["revoked"],
            "a rejected revocation must not be half-applied",
        )

        self.svc.revoke_report(self.t1_admin, report_id)
        self.assertTrue(self.svc.get_report(self.t1_admin, report_id)["revoked"])

    def test_foreign_tenant_cannot_revoke_and_existence_is_not_disclosed(self):
        report_id = self.save(self.t1_analyst, "R")

        with self.assertRaises(NotFound):
            self.svc.revoke_report(self.t2_admin, report_id, "hostile")

        self.assertFalse(self.svc.get_report(self.t1_analyst, report_id)["revoked"])

    def test_revoke_of_an_unknown_report_is_not_found(self):
        for report_id in ("0" * 32, "", None):
            with self.assertRaises(NotFound):
                self.svc.revoke_report(self.t1_admin, report_id)

    def test_revoke_writes_exactly_one_audit_row(self):
        report_id = self.save(self.t1_analyst, "R")
        self.svc.revoke_report(self.t1_admin, report_id, "policy")
        rows = [r for r in self.store.audit_rows(report_id) if r["action"] == "report.revoke"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["actor_id"], self.t1_admin.id)
        self.assertEqual(rows[0]["tenant_id"], "t1")

    # ------------------------------------------------- listing reports revocation truthfully

    def test_list_reports_reports_revocation_state_truthfully(self):
        revoked = self.save(self.t1_analyst, "Revoked")
        live = self.save(self.t1_analyst, "Live")
        self.svc.revoke_report(self.t1_admin, revoked)

        by_id = {r["id"]: r for r in self.svc.list_reports(self.t1_analyst)}
        self.assertEqual(set(by_id), {revoked, live})
        self.assertTrue(by_id[revoked]["revoked"], "a revoked report is listed as un-revoked")
        self.assertFalse(by_id[live]["revoked"])

    def test_revocation_does_not_change_the_stored_payload_bytes(self):
        """Second, independent check: compare the raw JSON string, not just the parsed value."""
        report_id = self.save(self.t1_analyst, "R", {"rows": 7})
        before = snapshot_row(self.store, report_id)["payload_json"]
        self.svc.revoke_report(self.t1_admin, report_id)
        after = snapshot_row(self.store, report_id)["payload_json"]
        self.assertEqual(json.loads(after), json.loads(before))
        self.assertEqual(after, before)
