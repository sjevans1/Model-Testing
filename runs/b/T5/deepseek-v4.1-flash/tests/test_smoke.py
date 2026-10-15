"""Visible smoke tests. These pass on the shipped tree; add your own tests alongside."""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from reportcore import DatasetRegistry, Store, User  # noqa: E402


def make_store() -> Store:
    store = Store()
    store.seed_tenant("t1", "Tenant One")
    store.seed_tenant("t2", "Tenant Two")
    return store


class TestDatasetRegistry(unittest.TestCase):
    def test_save_then_get_roundtrips(self):
        store = make_store()
        registry = DatasetRegistry(store)
        analyst = User(id="u1", tenant_id="t1", email="a@t1", role="analyst")
        dataset_id = registry.save_dataset(analyst, "Sales", {"rows": 3})
        got = registry.get_dataset(analyst, dataset_id)
        self.assertEqual(got["payload"], {"rows": 3})
        self.assertEqual(got["tenant_id"], "t1")


if __name__ == "__main__":
    unittest.main()
