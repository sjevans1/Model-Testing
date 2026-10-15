"""Smoke tests for the admin slice."""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from adminaccess.store import Store  # noqa: E402
from adminaccess.users import Actor, NotFound, StaleVersion, UserService  # noqa: E402


def svc():
    store = Store()
    store.add_user("u1", "t1", "ana@example.test", "viewer")
    return UserService(store), Actor(id="admin1", tenant_id="t1", role="admin")


class TestUserService(unittest.TestCase):
    def test_list_is_tenant_scoped(self):
        service, admin = svc()
        self.assertEqual([u["email"] for u in service.list_users(admin)], ["ana@example.test"])

    def test_change_role_persists_and_audits(self):
        service, admin = svc()
        row = service.change_role(admin, "u1", "analyst")
        self.assertEqual(row["role"], "analyst")
        self.assertEqual(row["version"], 2)


if __name__ == "__main__":
    unittest.main()
