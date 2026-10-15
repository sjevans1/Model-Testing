"""Input validation, role gates and fail-closed behaviour ("invalid inputs",
"unauthorized access", "role changes and revocation").

The three CLAIMS.md claims do not spell out input validation or the save-side role gate,
but README "Conventions" 1 and 2 do, and the reference feature ``DatasetRegistry`` in the
same module implements exactly them ("The SavedReportsService below follows exactly these
conventions").  These tests pin that contract; the convention-derived ones are flagged in
test-plan.md.

An unknown role must fail *closed*: ``models.role_level`` documents that unknown roles rank
below every real role, and CLAIM 1 forbids a caller from gaining access they were not
granted.
"""
from __future__ import annotations

from reportcore import DatasetRegistry, Forbidden, NotFound, ValidationError

from support import SavedReportsCase, admin, analyst, count, report_row, snapshot_row, user, viewer


class InputValidation(SavedReportsCase):

    def assert_no_report_was_written(self):
        self.assertEqual(count(self.store, "reports"), 0, "an invalid request wrote a report")
        self.assertEqual(count(self.store, "report_snapshots"), 0, "an invalid request wrote a snapshot")

    def test_name_must_be_a_non_empty_string(self):
        for bad_name in (None, "", "   ", 42, ["n"], {"name": "x"}):
            with self.subTest(name=bad_name):
                with self.assertRaises(ValidationError):
                    self.svc.save_report(self.t1_analyst, bad_name, {"rows": 1})
                self.assert_no_report_was_written()

    def test_payload_must_be_an_object(self):
        for bad_payload in (None, "text", 42, ["a"], ("t",)):
            with self.subTest(payload=bad_payload):
                with self.assertRaises(ValidationError):
                    self.svc.save_report(self.t1_analyst, "N", bad_payload)
                self.assert_no_report_was_written()

    def test_classification_must_be_a_known_value(self):
        for bad_classification in ("secret", "Confidential", "", "INTERNAL", None, 7):
            with self.subTest(classification=bad_classification):
                with self.assertRaises(ValidationError):
                    self.svc.save_report(self.t1_admin, "N", {"rows": 1}, bad_classification)
                self.assert_no_report_was_written()

    def test_name_is_trimmed(self):
        report_id = self.save(self.t1_analyst, "  Sales  ")
        self.assertEqual(self.svc.get_report(self.t1_analyst, report_id)["name"], "Sales")

    def test_unknown_report_ids_are_not_found(self):
        for report_id in ("0" * 32, "", None):
            with self.subTest(report_id=report_id):
                with self.assertRaises(NotFound):
                    self.svc.get_report(self.t1_analyst, report_id)


class RoleGates(SavedReportsCase):

    def test_saving_requires_at_least_analyst(self):
        with self.assertRaises(Forbidden):
            self.svc.save_report(self.t1_viewer, "N", {"rows": 1})
        self.assertEqual(count(self.store, "reports"), 0)

        self.assertIsInstance(self.svc.save_report(self.t1_analyst, "N", {"rows": 1}), str)
        self.assertIsInstance(self.svc.save_report(self.t1_admin, "N2", {"rows": 1}), str)

    def test_creating_a_confidential_report_requires_an_admin(self):
        with self.assertRaises(Forbidden):
            self.svc.save_report(self.t1_analyst, "N", {"rows": 1}, "confidential")
        self.assertEqual(count(self.store, "reports"), 0)

        report_id = self.svc.save_report(self.t1_admin, "N", {"rows": 1}, "confidential")
        self.assertEqual(report_row(self.store, report_id)["classification"], "confidential")

    def test_unknown_role_fails_closed_everywhere(self):
        """An unrecognised role must be treated as the lowest rank, not waved through."""
        impostor = user("u-impostor", "t1", "root")

        with self.assertRaises(Forbidden):
            self.svc.save_report(impostor, "N", {"rows": 1})

        report_id = self.save(self.t1_admin, "C", {"rows": 1}, "confidential")
        with self.assertRaises(Forbidden):
            self.svc.get_report(impostor, report_id)

        registry = DatasetRegistry(self.store)
        with self.assertRaises(Forbidden):
            registry.save_dataset(impostor, "D", {"rows": 1})
        with self.assertRaises(Forbidden):
            registry.save_dataset(impostor, "D2", {"rows": 1}, "confidential")

        self.assertEqual(count(self.store, "reports"), 1)

    def test_role_change_is_respected_on_the_next_call(self):
        """Role is read from the authenticated principal each call: a demotion takes effect."""
        report_id = self.save(self.t1_admin, "N", {"rows": 1})

        promoted = user(self.t1_admin.id, "t1", "admin")
        self.svc.revoke_report(promoted, report_id)
        self.assertTrue(self.svc.get_report(self.t1_admin, report_id)["revoked"])

        demoted = user(self.t1_admin.id, "t1", "viewer")
        other = self.save(self.t1_analyst, "M", {"rows": 2})
        with self.assertRaises(Forbidden):
            self.svc.revoke_report(demoted, other, "demoted attempt")
        self.assertFalse(self.svc.get_report(self.t1_analyst, other)["revoked"])

    def test_a_demoted_admin_can_no_longer_read_confidential_reports(self):
        report_id = self.save(self.t1_admin, "C", {"rows": 1}, "confidential")
        demoted = user(self.t1_admin.id, "t1", "analyst")
        with self.assertRaises(Forbidden):
            self.svc.get_report(demoted, report_id)


class PayloadCannotEscalate(SavedReportsCase):

    def test_payload_cannot_forge_owner_or_role(self):
        report_id = self.svc.save_report(
            self.t1_analyst,
            "N",
            {"owner_id": "someone-else", "role": "admin", "tenant_id": "t1", "rows": 1},
        )
        row = report_row(self.store, report_id)
        self.assertEqual(row["owner_id"], self.t1_analyst.id)
        self.assertEqual(row["tenant_id"], "t1")
        self.assertEqual(row["classification"], "internal")

    def test_payload_cannot_ask_for_a_confidential_classification(self):
        """Classification is a parameter of the call, not something the payload can set."""
        report_id = self.svc.save_report(
            self.t1_analyst, "N", {"classification": "confidential", "rows": 1}
        )
        self.assertEqual(report_row(self.store, report_id)["classification"], "internal")
        self.assertEqual(self.svc.get_report(self.t1_viewer, report_id)["payload"]["rows"], 1)

    def test_snapshot_is_written_exactly_once_per_save(self):
        report_id = self.save(self.t1_analyst, "N")
        self.assertEqual(count(self.store, "report_snapshots"), 1)
        self.assertIsNotNone(snapshot_row(self.store, report_id))


class FixturesAreSane(SavedReportsCase):
    """Guards the harness itself: if these fail, every other test in the suite is suspect."""

    def test_actors_have_distinct_tenants_and_roles(self):
        self.assertEqual(admin("t1").tenant_id, "t1")
        self.assertEqual(analyst("t2").tenant_id, "t2")
        self.assertEqual(viewer("t1").role, "viewer")
        self.assertNotEqual(analyst("t1").id, analyst("t2").id)

    def test_seeded_tenants_exist(self):
        self.assertEqual(self.store.fetchone("SELECT COUNT(*) AS n FROM tenants")["n"], 2)
