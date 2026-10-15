"""Post-PR tests for the role service."""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from roleservice import RoleService, Store  # noqa: E402


def svc():
    store = Store()
    store.conn.execute("INSERT INTO users(id, tenant_id, role, version) VALUES ('u1', 't1', 'viewer', 1)")
    store.conn.execute("INSERT INTO users(id, tenant_id, role, version) VALUES ('u2', 't2', 'viewer', 1)")
    store.conn.commit()
    return RoleService(store)


ADMIN = {"id": "a1", "tenant_id": "t1", "role": "admin"}


class TestRoleService(unittest.TestCase):
    def test_admin_can_request(self):
        request_id = svc().request_role_change(ADMIN, "u1", "analyst")
        self.assertTrue(request_id)

    def test_approve_applies_the_role(self):
        service = svc()
        request_id = service.request_role_change(ADMIN, "u1", "analyst")
        service.approve(ADMIN, request_id)
        row = service.store.conn.execute("SELECT role FROM users WHERE id = 'u1'").fetchone()
        self.assertEqual(row["role"], "analyst")

    def test_bulk_apply_reports_completion(self):
        service = svc()
        result = service.apply_bulk(ADMIN, [{"user_id": "u1", "role": "admin"}])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["applied"], 1)
