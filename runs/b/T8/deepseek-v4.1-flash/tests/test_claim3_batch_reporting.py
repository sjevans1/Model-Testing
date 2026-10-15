"""CLAIM 3 (truthful batch reporting).

CLAIMS.md: "`save_batch()` reports the truth about a batch: the count it returns is the
count that was actually saved, and `status` is `complete` only when every item was saved."

Every assertion here compares the returned summary with ground truth read back from the
store (row counts and the ids that are actually retrievable), never with the summary
itself.  A batch that swallows a failure and still reports ``complete``, or that returns a
count it did not save, fails these tests.
"""
from __future__ import annotations

from reportcore import Forbidden, NotFound, ValidationError

from support import SavedReportsCase, count, report_row, snapshot_row


def item(name: str, payload=None, classification: str = "internal") -> dict:
    return {
        "name": name,
        "payload": {"rows": 1} if payload is None else payload,
        "classification": classification,
    }


class Claim3BatchReporting(SavedReportsCase):

    def saved_count(self, tenant_id: str = "t1") -> int:
        """Ground truth: reports actually persisted for a tenant."""
        return self.store.fetchone(
            "SELECT COUNT(*) AS n FROM reports WHERE tenant_id = ?", (tenant_id,)
        )["n"]

    # ------------------------------------------------------------------ happy path

    def test_all_valid_batch_reports_complete_and_the_true_count(self):
        items = [item("A", {"rows": 1}), item("B", {"rows": 2}), item("C", {"rows": 3})]
        result = self.svc.save_batch(self.t1_analyst, items)

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["applied"], 3)
        self.assertEqual(len(result["saved"]), 3)
        self.assertEqual(self.saved_count(), 3, "the batch did not persist what it reported")

    def test_every_saved_id_is_readable_and_carries_the_right_content(self):
        items = [item("A", {"rows": 1}), item("B", {"rows": 2})]
        result = self.svc.save_batch(self.t1_analyst, items)

        by_name = {}
        for report_id in result["saved"]:
            got = self.svc.get_report(self.t1_analyst, report_id)
            by_name[got["name"]] = got["payload"]
        self.assertEqual(by_name, {"A": {"rows": 1}, "B": {"rows": 2}})
        self.assertEqual(len(set(result["saved"])), len(result["saved"]), "duplicate ids returned")

        for report_id in result["saved"]:
            self.assertIsNotNone(snapshot_row(self.store, report_id))

    def test_empty_batch_saves_nothing_and_does_not_crash(self):
        result = self.svc.save_batch(self.t1_analyst, [])
        self.assertEqual(result["applied"], 0)
        self.assertEqual(result["saved"], [])
        self.assertEqual(self.saved_count(), 0)
        self.assertEqual(count(self.store, "report_snapshots"), 0)

    # ------------------------------------------------------- partial / failing batches

    def test_partial_batch_is_not_reported_as_complete(self):
        """One invalid item means `status` may not be `complete`."""
        items = [item("Good"), item("", {"rows": 9}), item("Also good")]
        result = self.svc.save_batch(self.t1_analyst, items)

        self.assertNotEqual(
            result["status"], "complete",
            "the batch claims to be complete although one of its items was rejected",
        )

    def test_partial_batch_count_equals_what_was_actually_saved(self):
        items = [item("Good"), item("", {"rows": 9}), item("Also good")]
        result = self.svc.save_batch(self.t1_analyst, items)

        self.assertEqual(result["applied"], 2)
        self.assertEqual(len(result["saved"]), 2)
        self.assertEqual(self.saved_count(), 2, "reported count disagrees with the store")

        names = sorted(self.svc.get_report(self.t1_analyst, rid)["name"] for rid in result["saved"])
        self.assertEqual(names, ["Also good", "Good"])

    def test_partial_batch_does_not_persist_the_rejected_item(self):
        items = [item("Good"), item("", {"rows": 9})]
        self.svc.save_batch(self.t1_analyst, items)

        rows = self.store.fetchall("SELECT * FROM reports")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("", [r["name"] for r in rows])
        self.assertEqual(count(self.store, "report_snapshots"), 1)

    def test_batch_of_only_invalid_items_never_reports_them_as_saved(self):
        items = [item("", {"rows": 1}), item("   ", {"rows": 2})]
        try:
            result = self.svc.save_batch(self.t1_analyst, items)
        except ValidationError:
            # Rejecting the whole malformed batch outright is an acceptable contract too.
            result = None

        if result is not None:
            self.assertNotEqual(result["status"], "complete")
            self.assertEqual(result["applied"], 0)
            self.assertEqual(result["saved"], [])
        self.assertEqual(self.saved_count(), 0, "invalid items were persisted anyway")

    def test_batch_with_a_malformed_item_never_over_reports(self):
        """A non-object item cannot be saved, so the batch may not claim it was."""
        try:
            result = self.svc.save_batch(self.t1_analyst, ["not-an-object"])
        except ValidationError:
            result = None

        if result is not None:
            self.assertNotEqual(result["status"], "complete")
            self.assertEqual(result["applied"], 0)
            self.assertEqual(result["saved"], [])
        self.assertEqual(self.saved_count(), 0)

    def test_mixed_malformed_and_valid_batch_reports_partial_truthfully(self):
        try:
            result = self.svc.save_batch(self.t1_analyst, [item("Good"), "not-an-object", None])
        except ValidationError:
            # Only reachable if the implementation rejects the whole request; the store must
            # then not be in a state that contradicts a rejection.
            result = None

        if result is not None:
            actual = self.saved_count()
            self.assertLessEqual(actual, 1, "only the single well-formed item may be persisted")
            self.assertEqual(result["applied"], actual)
            self.assertEqual(len(result["saved"]), actual)
            self.assertNotEqual(
                result["status"], "complete",
                "two of the three items were not saved, so the batch is not complete",
            )
        self.assertLessEqual(self.saved_count(), 1)

    # ------------------------------------------------ the batch is not a privilege bypass

    def test_batch_items_cannot_choose_their_tenant(self):
        items = [
            item("A", {"tenant_id": "t2", "rows": 1}),
            item("B", {"tenant_id": "t2", "rows": 2}),
        ]
        result = self.svc.save_batch(self.t1_analyst, items)

        self.assertEqual(result["applied"], 2)
        for report_id in result["saved"]:
            self.assertEqual(report_row(self.store, report_id)["tenant_id"], "t1")
            with self.assertRaises(NotFound):
                self.svc.get_report(self.t2_admin, report_id)
        self.assertEqual(self.saved_count("t2"), 0)

    def test_batch_item_cannot_grant_itself_a_higher_classification(self):
        """An analyst may not create a confidential report by smuggling it through a batch."""
        items = [item("Sneaky", classification="confidential")]
        result = self.svc.save_batch(self.t1_analyst, items)

        self.assertEqual(result["applied"], 0)
        self.assertNotEqual(result["status"], "complete")
        self.assertEqual(self.saved_count(), 0)

    def test_batch_requires_authorisation_like_a_single_save(self):
        """Either the batch is refused outright, or it reports that nothing was saved."""
        items = [item("A")]
        try:
            result = self.svc.save_batch(self.t1_viewer, items)
        except Forbidden:
            pass
        else:
            self.assertEqual(result["applied"], 0, "a viewer's batch reported saves")
            self.assertEqual(result["saved"], [])
            self.assertNotEqual(result["status"], "complete")
        self.assertEqual(self.saved_count(), 0, "a viewer's batch persisted a report")
        self.assertEqual(count(self.store, "report_snapshots"), 0)
