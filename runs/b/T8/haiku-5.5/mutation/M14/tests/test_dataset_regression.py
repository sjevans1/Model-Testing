"""Regression guard for DatasetRegistry, which CLAIMS.md says is believed correct."""
from __future__ import annotations

import unittest

from reportcore import Forbidden, NotFound

from _support import ServiceTestCase


class TestDatasetRegistryRegression(ServiceTestCase):
    def test_round_trip_keeps_payload_and_hash(self):
        ds = self.datasets.save_dataset(self.t1_analyst, "Sales", {"rows": 3})
        got = self.datasets.get_dataset(self.t1_analyst, ds)
        self.assertEqual(got["payload"], {"rows": 3})
        self.assertEqual(got["version"], 1)
        self.assertEqual(len(got["content_hash"]), 64)

    def test_viewer_cannot_save_dataset(self):
        with self.assertRaises(Forbidden):
            self.datasets.save_dataset(self.t1_viewer, "Sales", {"rows": 3})

    def test_confidential_dataset_hidden_from_analyst(self):
        ds = self.datasets.save_dataset(self.t1_admin, "Pay", {"x": 1}, "confidential")
        with self.assertRaises(Forbidden):
            self.datasets.get_dataset(self.t1_analyst, ds)

    def test_foreign_tenant_gets_not_found(self):
        ds = self.datasets.save_dataset(self.t1_analyst, "Sales", {"rows": 3})
        with self.assertRaises(NotFound):
            self.datasets.get_dataset(self.t2_admin, ds)

    def test_list_is_tenant_scoped(self):
        self.datasets.save_dataset(self.t1_analyst, "T1 DS", {"a": 1})
        self.datasets.save_dataset(self.t2_analyst, "T2 DS", {"a": 1})
        names = {r["name"] for r in self.datasets.list_datasets(self.t1_analyst)}
        self.assertEqual(names, {"T1 DS"})


if __name__ == "__main__":
    unittest.main()
