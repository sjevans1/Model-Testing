"""Claim 3: save_batch() reports the truth about a batch.

The count it returns must equal the number of reports actually saved, and status must be
"complete" only when every item was saved. Failed or partial batches must say so.

Return shape (from the implementation): {"applied": <count>, "saved": [<report ids>], "status": <str>}.
The claim fixes the meaning of the count, not the status vocabulary, so the tests only
require that a non-complete batch has some status other than "complete".
"""
from __future__ import annotations

import unittest

from _support import ServiceTestCase, item


class TestBatchNormal(ServiceTestCase):
    def test_all_valid_items_saved_and_reported_complete(self):
        result = self.reports.save_batch(
            self.t1_analyst, [item("A"), item("B"), item("C")]
        )
        self.assertEqual(len(result["saved"]), 3)
        self.assertEqual(result["applied"], 3)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.count_reports("t1"), 3)

    def test_returned_ids_are_real_reports_owned_by_the_actor_tenant(self):
        result = self.reports.save_batch(self.t1_analyst, [item("A"), item("B")])
        for rid in result["saved"]:
            row = self.report_row(rid)
            self.assertIsNotNone(row, rid)
            self.assertEqual(row["tenant_id"], "t1")
            self.assertEqual(row["owner_id"], self.t1_analyst.id)

    def test_empty_batch_saves_nothing(self):
        result = self.reports.save_batch(self.t1_analyst, [])
        self.assertEqual(result["saved"], [])
        self.assertEqual(result["applied"], 0)
        self.assertEqual(self.count_reports("t1"), 0)


class TestBatchPartialFailure(ServiceTestCase):
    def test_invalid_item_is_not_counted_and_status_is_not_complete(self):
        result = self.reports.save_batch(
            self.t1_analyst, [item("Good"), item("   "), item("Also good")]
        )
        self.assertEqual(self.count_reports("t1"), 2, "exactly two rows were written")
        self.assertEqual(len(result["saved"]), 2)
        self.assertEqual(result["applied"], len(result["saved"]))
        self.assertNotEqual(result["status"], "complete")

    def test_unauthorised_item_is_not_counted_as_saved(self):
        # A viewer's batch: every item is a Forbidden write, so nothing is saved.
        result = self.reports.save_batch(self.t1_viewer, [item("X"), item("Y")])
        self.assertEqual(self.count_reports("t1"), 0)
        self.assertEqual(result["saved"], [])
        self.assertEqual(result["applied"], 0)
        self.assertNotEqual(result["status"], "complete")

    def test_confidential_item_rejected_for_analyst_is_not_counted(self):
        result = self.reports.save_batch(
            self.t1_analyst,
            [item("Public"), item("Secret", classification="confidential")],
        )
        self.assertEqual(self.count_reports("t1"), 1)
        self.assertEqual(len(result["saved"]), 1)
        self.assertEqual(result["applied"], 1)
        self.assertNotEqual(result["status"], "complete")

    def test_all_items_failing_reports_zero_and_not_complete(self):
        result = self.reports.save_batch(self.t1_analyst, [item(""), item(None)])
        self.assertEqual(self.count_reports("t1"), 0)
        self.assertEqual(result["applied"], 0)
        self.assertEqual(result["saved"], [])
        self.assertNotEqual(result["status"], "complete")

    def test_failed_items_leave_no_partial_rows_behind(self):
        # Each reported id must correspond to a stored row, and every stored row must be reported.
        result = self.reports.save_batch(
            self.t1_analyst, [item("A"), item(""), item("B"), item("C", payload=["bad"])]
        )
        stored = self.store.fetchall("SELECT id FROM reports WHERE tenant_id = 't1'")
        self.assertEqual({r["id"] for r in stored}, set(result["saved"]))


class TestBatchTenantAndInjection(ServiceTestCase):
    def test_tenant_id_in_batch_payload_is_ignored(self):
        result = self.reports.save_batch(
            self.t1_analyst, [item("Smuggled", payload={"rows": 1, "tenant_id": "t2"})]
        )
        self.assertEqual(len(result["saved"]), 1)
        self.assertEqual(self.report_row(result["saved"][0])["tenant_id"], "t1")
        self.assertEqual(self.count_reports("t2"), 0)


class TestBatchShapeErrors(ServiceTestCase):
    def test_non_dict_items_are_not_reported_as_saved(self):
        result = self.reports.save_batch(self.t1_analyst, [None, "junk", item("OK")])
        self.assertEqual(self.count_reports("t1"), len(result["saved"]))
        self.assertEqual(result["applied"], len(result["saved"]))
        self.assertNotEqual(result["status"], "complete")


if __name__ == "__main__":
    unittest.main()
