"""Duplicate submissions and concurrent/conflicting updates.

Two things are checked:

1. Duplicates are genuinely independent records.  Saving the same content twice must not
   alias the two reports into one (a plausible "optimisation" is to key the snapshot by
   content hash); revoking one must leave the other untouched.
2. Concurrent use of the service from several threads (one sqlite connection each, which is
   how a real caller would use it) neither corrupts nor loses data, and readers never
   observe a torn report (an existing report with a missing or rewritten snapshot).

The threaded test is the one part of this suite whose failure mode is not a wrong return
value but a crash/lock/tearing; its sensitivity is demonstrated in test-plan.md with
mutation M16 (a Store that shares one connection across threads).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import unittest

from reportcore import ReportCoreError, SavedReportsService

from support import (
    SavedReportsCase,
    admin,
    canonical_json,
    content_hash,
    count,
    make_store,
    snapshot_fingerprint,
)


class DuplicateSubmissions(SavedReportsCase):

    def test_identical_submissions_create_two_independent_reports(self):
        payload = {"rows": 3, "cols": 2}
        first = self.save(self.t1_analyst, "Same", payload)
        second = self.save(self.t1_analyst, "Same", payload)

        self.assertNotEqual(first, second)
        self.assertEqual(count(self.store, "reports"), 2)
        self.assertEqual(count(self.store, "report_snapshots"), 2)

        for report_id in (first, second):
            got = self.svc.get_report(self.t1_analyst, report_id)
            self.assertEqual(got["payload"], payload)
            self.assertEqual(got["content_hash"], content_hash(payload))

    def test_duplicate_submission_does_not_share_revocation_state(self):
        payload = {"rows": 3, "cols": 2}
        first = self.save(self.t1_analyst, "Same", payload)
        second = self.save(self.t1_analyst, "Same", payload)

        self.svc.revoke_report(self.t1_admin, first)

        self.assertTrue(self.svc.get_report(self.t1_analyst, first)["revoked"])
        self.assertFalse(self.svc.get_report(self.t1_analyst, second)["revoked"])

    def test_batch_containing_duplicate_items_saves_each_one(self):
        items = [
            {"name": "Same", "payload": {"rows": 1}},
            {"name": "Same", "payload": {"rows": 1}},
            {"name": "Same", "payload": {"rows": 1}},
        ]
        result = self.svc.save_batch(self.t1_analyst, items)

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["applied"], 3)
        self.assertEqual(len(set(result["saved"])), 3)
        self.assertEqual(count(self.store, "reports"), 3)
        for report_id in result["saved"]:
            self.svc.get_report(self.t1_analyst, report_id)


class ConcurrentUpdates(unittest.TestCase):
    """Uses a file-backed store so that each thread can hold its own sqlite connection."""

    READERS = 3
    READS_PER_READER = 25
    REVOKES = 3

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="reportcore-t8-")
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.path = os.path.join(self.tmpdir, "reports.sqlite3")

        seed = make_store(self.path)
        self.actor = admin("t1")
        self.payload = {"rows": 1, "note": "shared"}
        self.report_id = SavedReportsService(seed).save_report(self.actor, "Shared", self.payload)
        self.hash = content_hash(self.payload)
        self.fingerprint = snapshot_fingerprint(seed, self.report_id)

    def test_concurrent_revocations_and_reads_leave_a_consistent_report(self):
        errors = []
        observations = []
        lock = threading.Lock()

        def record(role, exc):
            with lock:
                errors.append((role, type(exc).__name__, str(exc)))

        def revoker():
            try:
                # A connection belongs to the thread that made it, so every worker opens its
                # own Store - a service that shares one connection (or any other unsynchronised
                # state) across threads fails here.
                service = SavedReportsService(make_store(self.path))
                for _ in range(self.REVOKES):
                    try:
                        service.revoke_report(self.actor, self.report_id, "concurrent")
                    except ReportCoreError:
                        pass  # a rejected duplicate revocation is acceptable
            except BaseException as exc:  # noqa: BLE001 - recorded, then asserted on
                record("revoker", exc)

        def reader():
            try:
                service = SavedReportsService(make_store(self.path))
                for _ in range(self.READS_PER_READER):
                    got = service.get_report(self.actor, self.report_id)
                    with lock:
                        observations.append(
                            (got["content_hash"], canonical_json(got["payload"]), got["revoked"])
                        )
                    time.sleep(0)
            except BaseException as exc:  # noqa: BLE001 - recorded, then asserted on
                record("reader", exc)

        threads = [threading.Thread(target=revoker)]
        threads += [threading.Thread(target=reader) for _ in range(self.READERS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertFalse(any(t.is_alive() for t in threads), "a worker thread never finished")
        self.assertEqual(errors, [], f"concurrent use of the service raised: {errors[:5]}")
        self.assertTrue(observations, "the readers observed nothing at all")

        for content_hash_seen, payload_seen, _ in observations:
            self.assertEqual(content_hash_seen, self.hash, "a reader saw a different content hash")
            self.assertEqual(payload_seen, canonical_json(self.payload), "a reader saw a torn snapshot")

        final_store = make_store(self.path)
        final = SavedReportsService(final_store)
        self.assertTrue(final.get_report(self.actor, self.report_id)["revoked"])
        self.assertEqual(snapshot_fingerprint(final_store, self.report_id), self.fingerprint)
        self.assertEqual(count(final_store, "report_snapshots"), 1)
        self.assertEqual(count(final_store, "reports"), 1)

        revoke_audits = [
            r for r in final_store.audit_rows(self.report_id) if r["action"] == "report.revoke"
        ]
        self.assertGreaterEqual(len(revoke_audits), 1, "the revocation left no audit row")
