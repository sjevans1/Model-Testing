"""Regression guard for ``DatasetRegistry`` (the reference feature, believed correct).

CLAIMS.md: "The `DatasetRegistry` feature in the same module is believed correct and should
not regress."  These tests pin the behaviour the SavedReports service is supposed to mirror,
so that a future "fix" that breaks the reference feature is caught.

They pass on the shipped tree; the one shared-primitive bug the shipped tree *does* have
(an unknown role failing open) is asserted in test_inputs_and_authorization.py, not here.
"""
from __future__ import annotations

from reportcore import DatasetRegistry, Forbidden, NotFound, ValidationError

from support import SavedReportsCase, count


class DatasetRegistryContracts(SavedReportsCase):

    def setUp(self):
        super().setUp()
        self.registry = DatasetRegistry(self.store)

    def test_save_and_get_roundtrip(self):
        dataset_id = self.registry.save_dataset(self.t1_analyst, "Sales", {"rows": 3})
        got = self.registry.get_dataset(self.t1_analyst, dataset_id)
        self.assertEqual(got["payload"], {"rows": 3})
        self.assertEqual(got["tenant_id"], "t1")
        self.assertEqual(got["owner_id"], self.t1_analyst.id)
        self.assertEqual(got["version"], 1)
        self.assertEqual(count(self.store, "dataset_versions"), 1)

    def test_foreign_tenant_read_is_not_found(self):
        dataset_id = self.registry.save_dataset(self.t1_analyst, "Sales", {"rows": 3})
        with self.assertRaises(NotFound):
            self.registry.get_dataset(self.t2_admin, dataset_id)

    def test_version_is_immutable_across_reads(self):
        dataset_id = self.registry.save_dataset(self.t1_analyst, "Sales", {"rows": 3, "cols": 2})
        before = self.store.fetchall("SELECT * FROM dataset_versions WHERE dataset_id = ?", (dataset_id,))
        first = self.registry.get_dataset(self.t1_analyst, dataset_id)
        second = self.registry.get_dataset(self.t1_admin, dataset_id)
        self.assertEqual(first["content_hash"], second["content_hash"])
        after = self.store.fetchall("SELECT * FROM dataset_versions WHERE dataset_id = ?", (dataset_id,))
        self.assertEqual([dict(r) for r in before], [dict(r) for r in after])

    def test_write_requires_analyst_and_confidential_requires_admin(self):
        with self.assertRaises(Forbidden):
            self.registry.save_dataset(self.t1_viewer, "D", {"rows": 1})
        with self.assertRaises(Forbidden):
            self.registry.save_dataset(self.t1_analyst, "D", {"rows": 1}, "confidential")
        self.assertIsInstance(self.registry.save_dataset(self.t1_admin, "D", {"rows": 1}), str)

    def test_invalid_input_is_rejected_before_the_store(self):
        for name, payload, classification in (
            ("", {"rows": 1}, "internal"),
            ("D", "not-an-object", "internal"),
            ("D", {"rows": 1}, "secret"),
        ):
            with self.subTest(name=name, classification=classification):
                with self.assertRaises(ValidationError):
                    self.registry.save_dataset(self.t1_analyst, name, payload, classification)
                self.assertEqual(count(self.store, "datasets"), 0)

    def test_confidential_dataset_is_admin_only(self):
        dataset_id = self.registry.save_dataset(self.t1_admin, "Board", {"rows": 1}, "confidential")
        with self.assertRaises(Forbidden):
            self.registry.get_dataset(self.t1_analyst, dataset_id)
        self.assertEqual(self.registry.get_dataset(self.t1_admin, dataset_id)["payload"], {"rows": 1})

    def test_list_is_scoped_and_filtered(self):
        internal_id = self.registry.save_dataset(self.t1_analyst, "Internal", {"rows": 1})
        confidential_id = self.registry.save_dataset(self.t1_admin, "Confidential", {"rows": 2}, "confidential")
        other_tenant_id = self.registry.save_dataset(self.t2_analyst, "Other", {"rows": 3})

        for actor in (self.t1_viewer, self.t1_analyst):
            visible = [r["id"] for r in self.registry.list_datasets(actor)]
            self.assertIn(internal_id, visible)
            self.assertNotIn(confidential_id, visible)
            self.assertNotIn(other_tenant_id, visible)

    def test_reads_are_audited(self):
        dataset_id = self.registry.save_dataset(self.t1_analyst, "Sales", {"rows": 3})
        self.registry.get_dataset(self.t1_analyst, dataset_id)
        actions = [r["action"] for r in self.store.audit_rows(dataset_id)]
        self.assertEqual(actions, ["dataset.save", "dataset.read"])

    def test_the_two_features_do_not_share_rows(self):
        """A dataset and a report must live in their own tables (no accidental union)."""
        self.registry.save_dataset(self.t1_analyst, "Sales", {"rows": 3})
        self.assertEqual(count(self.store, "reports"), 0)
        with self.assertRaises(NotFound):
            self.svc.get_report(self.t1_analyst, "0" * 32)
