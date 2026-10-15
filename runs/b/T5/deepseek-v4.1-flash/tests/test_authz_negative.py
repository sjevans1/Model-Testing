"""Negative authorization tests for SavedReportsService.

Every test in this file is written against the required behaviour:

* a report and its snapshot are readable only by members of the owning tenant, and
  a foreign-tenant error must be indistinguishable from a missing object;
* revocation is tenant-scoped and limited to the owner or a tenant admin;
* tenant and owner come from the authenticated actor, never from the payload;
* ``confidential`` reports are readable only by tenant admins;
* every mutation and privileged read is audited;
* an unknown, empty or unrecognised role is denied everywhere (fail closed);
* ``save_batch`` reports the truth about what it saved.

These tests fail on the tree as shipped and pass on the corrected tree.  They are
deliberately negative: each one attempts the thing that must not be allowed.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from reportcore import (  # noqa: E402
    DatasetRegistry,
    Forbidden,
    NotFound,
    ReportCoreError,
    SavedReportsService,
    Store,
    User,
    ValidationError,
)

UNKNOWN_ROLES = ("", "   ", "superuser", "root", "ADMIN", None)


def make_store() -> Store:
    store = Store()
    store.seed_tenant("t1", "Tenant One")
    store.seed_tenant("t2", "Tenant Two")
    return store


def user(uid="u1", tenant="t1", role="analyst") -> User:
    return User(id=uid, tenant_id=tenant, email=f"{uid}@{tenant}", role=role)


def count_reports(store: Store, tenant_id: str) -> int:
    row = store.fetchone(
        "SELECT COUNT(*) AS n FROM reports WHERE tenant_id = ?", (tenant_id,)
    )
    return int(row["n"])


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.store = make_store()
        self.svc = SavedReportsService(self.store)

    def seed_report(self, actor: User, name="Q3", payload=None, classification="internal") -> str:
        return self.svc.save_report(actor, name, payload or {"rows": 1}, classification)


# ---------------------------------------------------------------------------
# 1. tenant isolation on reads
# ---------------------------------------------------------------------------
class TestTenantIsolationReads(Base):
    def test_get_report_in_other_tenant_is_not_found(self):
        owner = user("u1", "t1", "analyst")
        report_id = self.seed_report(owner)
        intruder = user("u2", "t2", "admin")  # even a *tenant admin* of t2
        with self.assertRaises(NotFound):
            self.svc.get_report(intruder, report_id)

    def test_foreign_tenant_error_is_indistinguishable_from_missing_object(self):
        owner = user("u1", "t1", "analyst")
        report_id = self.seed_report(owner)
        intruder = user("u2", "t2", "analyst")

        with self.assertRaises(NotFound) as foreign:
            self.svc.get_report(intruder, report_id)
        with self.assertRaises(NotFound) as missing:
            self.svc.get_report(intruder, "does-not-exist")

        self.assertEqual(type(foreign.exception), type(missing.exception))
        self.assertEqual(str(foreign.exception), str(missing.exception))

    def test_get_report_never_returns_another_tenants_snapshot(self):
        owner = user("u1", "t1", "analyst")
        report_id = self.seed_report(owner, payload={"secret": "t1-only"})
        intruder = user("u2", "t2", "analyst")
        result = None
        try:
            result = self.svc.get_report(intruder, report_id)
        except ReportCoreError:
            pass
        self.assertIsNone(result, "cross-tenant read returned content")

    def test_own_tenant_member_can_still_read(self):
        owner = user("u1", "t1", "analyst")
        colleague = user("u3", "t1", "viewer")
        report_id = self.seed_report(owner)
        self.assertEqual(self.svc.get_report(colleague, report_id)["payload"], {"rows": 1})

    def test_list_reports_is_tenant_scoped(self):
        self.seed_report(user("u1", "t1", "analyst"), name="one")
        self.seed_report(user("u2", "t2", "analyst"), name="two")
        listed = self.svc.list_reports(user("u3", "t1", "viewer"))
        self.assertEqual([r["name"] for r in listed], ["one"])

    def test_list_reports_does_not_name_other_tenants_reports(self):
        self.seed_report(user("u2", "t2", "analyst"), name="two")
        self.assertEqual(self.svc.list_reports(user("u3", "t1", "viewer")), [])


# ---------------------------------------------------------------------------
# 2. revocation authorization
# ---------------------------------------------------------------------------
class TestRevocationAuthorization(Base):
    def test_cross_tenant_revoke_is_not_found(self):
        owner = user("u1", "t1", "analyst")
        report_id = self.seed_report(owner)
        other_admin = user("u2", "t2", "admin")
        with self.assertRaises(NotFound):
            self.svc.revoke_report(other_admin, report_id, "hostile")
        self.assertFalse(self.svc.get_report(owner, report_id)["revoked"])

    def test_cross_tenant_revoke_error_matches_missing_object(self):
        owner = user("u1", "t1", "analyst")
        report_id = self.seed_report(owner)
        other_admin = user("u2", "t2", "admin")
        with self.assertRaises(NotFound) as foreign:
            self.svc.revoke_report(other_admin, report_id, "hostile")
        with self.assertRaises(NotFound) as missing:
            self.svc.revoke_report(other_admin, "does-not-exist", "hostile")
        self.assertEqual(str(foreign.exception), str(missing.exception))

    def test_tenant_admin_may_revoke_any_report_in_the_tenant(self):
        owner = user("u1", "t1", "analyst")
        report_id = self.seed_report(owner)
        admin = user("u9", "t1", "admin")
        self.svc.revoke_report(admin, report_id, "unused")
        self.assertTrue(self.svc.get_report(owner, report_id)["revoked"])

    def test_owner_may_revoke_without_admin_role(self):
        owner = user("u1", "t1", "viewer")
        report_id = self.seed_report(user("u1", "t1", "analyst"))
        self.svc.revoke_report(owner, report_id, "mine")
        self.assertTrue(self.svc.get_report(owner, report_id)["revoked"])

    def test_non_owner_non_admin_may_not_revoke(self):
        owner = user("u1", "t1", "analyst")
        report_id = self.seed_report(owner)
        for role in ("viewer", "analyst"):
            bystander = user("u7", "t1", role)
            with self.assertRaises(Forbidden):
                self.svc.revoke_report(bystander, report_id, "not mine")
            self.assertFalse(self.svc.get_report(owner, report_id)["revoked"],
                             f"{role} revoked a report it does not own")


# ---------------------------------------------------------------------------
# 3. tenant / owner provenance
# ---------------------------------------------------------------------------
class TestProvenance(Base):
    def test_payload_tenant_id_cannot_move_a_report(self):
        actor = user("u1", "t1", "analyst")
        report_id = self.svc.save_report(actor, "stolen", {"tenant_id": "t2", "rows": 2})
        row = self.store.fetchone("SELECT tenant_id FROM reports WHERE id = ?", (report_id,))
        self.assertEqual(row["tenant_id"], "t1")
        self.assertNotIn(report_id, [r["id"] for r in self.svc.list_reports(user("u2", "t2", "analyst"))])

    def test_payload_owner_id_cannot_reassign_ownership(self):
        actor = user("u1", "t1", "analyst")
        report_id = self.svc.save_report(actor, "stolen", {"owner_id": "u2", "rows": 2})
        row = self.store.fetchone("SELECT owner_id FROM reports WHERE id = ?", (report_id,))
        self.assertEqual(row["owner_id"], "u1")

    def test_tenant_and_owner_come_from_the_actor(self):
        actor = user("u5", "t2", "analyst")
        report_id = self.svc.save_report(actor, "mine", {"rows": 3})
        got = self.svc.get_report(actor, report_id)
        self.assertEqual(got["tenant_id"], "t2")
        self.assertEqual(got["owner_id"], "u5")

    def test_moved_report_is_not_readable_from_the_claimed_tenant(self):
        intruder = user("u2", "t2", "analyst")
        victim = user("u1", "t1", "analyst")
        report_id = self.svc.save_report(victim, "r", {"tenant_id": "t2"})
        with self.assertRaises(NotFound):
            self.svc.get_report(intruder, report_id)


# ---------------------------------------------------------------------------
# 4. classification
# ---------------------------------------------------------------------------
class TestClassification(Base):
    def test_confidential_report_is_admin_only(self):
        admin = user("u9", "t1", "admin")
        report_id = self.seed_report(admin, classification="confidential")
        for role in ("viewer", "analyst"):
            actor = user("u1", "t1", role)
            with self.assertRaises(Forbidden):
                self.svc.get_report(actor, report_id)

    def test_admin_may_read_confidential(self):
        admin = user("u9", "t1", "admin")
        report_id = self.seed_report(admin, classification="confidential", payload={"c": 1})
        self.assertEqual(self.svc.get_report(admin, report_id)["payload"], {"c": 1})

    def test_confidential_report_is_hidden_from_the_tenant_list(self):
        self.seed_report(user("u1", "t1", "analyst"), name="open")
        self.seed_report(user("u9", "t1", "admin"), name="closed", classification="confidential")
        self.assertEqual([r["name"] for r in self.svc.list_reports(user("u1", "t1", "analyst"))], ["open"])
        self.assertEqual(
            sorted(r["name"] for r in self.svc.list_reports(user("u9", "t1", "admin"))),
            ["closed", "open"],
        )

    def test_confidential_read_is_forbidden_not_not_found(self):
        admin = user("u9", "t1", "admin")
        report_id = self.seed_report(admin, classification="confidential")
        with self.assertRaises(Forbidden):
            self.svc.get_report(user("u1", "t1", "analyst"), report_id)

    def test_unrecognised_classification_is_rejected_on_save(self):
        actor = user("u1", "t1", "analyst")
        for bogus in ("", "public", "top-secret", "Internal", None):
            with self.assertRaises(ValidationError):
                self.svc.save_report(actor, "x", {"rows": 1}, bogus)

    def test_analyst_cannot_create_a_confidential_report(self):
        with self.assertRaises(Forbidden):
            self.svc.save_report(user("u1", "t1", "analyst"), "x", {"rows": 1}, "confidential")

    def test_unvalidated_classification_cannot_be_stored(self):
        actor = user("u1", "t1", "analyst")
        try:
            self.svc.save_report(actor, "x", {"rows": 1}, "public")
        except ReportCoreError:
            pass
        row = self.store.fetchone(
            "SELECT COUNT(*) AS n FROM reports WHERE classification NOT IN ('internal','confidential')"
        )
        self.assertEqual(int(row["n"]), 0)


# ---------------------------------------------------------------------------
# 5. fail closed on unknown / empty / unrecognised roles
# ---------------------------------------------------------------------------
class TestFailClosedRoles(Base):
    """An unknown, empty or unrecognised role must never be granted anything.

    Mutations refuse the caller outright; reads and batches are denied in the
    fail-closed shape this codebase already uses for the dataset feature (an
    unrecognised role is granted no object and saves nothing).
    """

    def test_unknown_role_is_denied_on_every_entry_point(self):
        good = user("u1", "t1", "analyst")
        report_id = self.seed_report(good)
        for role in UNKNOWN_ROLES:
            stranger = user("u1", "t1", role)  # correct id and tenant, unusable role
            with self.subTest(role=role, entry="save_report"):
                with self.assertRaises(ReportCoreError):
                    self.svc.save_report(stranger, "x", {"rows": 1})
            with self.subTest(role=role, entry="get_report"):
                with self.assertRaises(ReportCoreError):
                    self.svc.get_report(stranger, report_id)
            with self.subTest(role=role, entry="revoke_report"):
                # even as the owner of the report
                with self.assertRaises(ReportCoreError):
                    self.svc.revoke_report(stranger, report_id, "x")
            with self.subTest(role=role, entry="list_reports"):
                self.assertEqual(self.svc.list_reports(stranger), [])
            with self.subTest(role=role, entry="save_batch"):
                result = self.svc.save_batch(stranger, [{"name": "x", "payload": {"i": 1}}])
                self.assertEqual(result["applied"], 0)
                self.assertEqual(result["saved"], [])
                self.assertNotEqual(result["status"], "complete")
        # nothing happened anywhere
        self.assertEqual(count_reports(self.store, "t1"), 1)
        self.assertFalse(self.svc.get_report(good, report_id)["revoked"])

    def test_unknown_role_never_reads_a_report_in_its_own_tenant(self):
        owner = user("u1", "t1", "analyst")
        report_id = self.seed_report(owner, payload={"secret": 1})
        for role in UNKNOWN_ROLES:
            stranger = user("u1", "t1", role)
            result = None
            try:
                result = self.svc.get_report(stranger, report_id)
            except ReportCoreError:
                pass
            self.assertIsNone(result)

    def test_unknown_role_saves_nothing(self):
        for role in UNKNOWN_ROLES:
            stranger = user("u9", "t1", role)
            try:
                self.svc.save_report(stranger, "x", {"rows": 1})
            except ReportCoreError:
                pass
        self.assertEqual(count_reports(self.store, "t1"), 0)

    def test_unrecognised_role_on_the_dataset_feature_is_denied_too(self):
        registry = DatasetRegistry(self.store)
        dataset_id = registry.save_dataset(user("u1", "t1", "analyst"), "d", {"rows": 1})
        for role in UNKNOWN_ROLES:
            stranger = user("u1", "t1", role)
            with self.assertRaises(ReportCoreError):
                registry.get_dataset(stranger, dataset_id)
            with self.assertRaises(ReportCoreError):
                registry.save_dataset(stranger, "d2", {"rows": 1})

    def test_known_roles_still_work(self):
        self.assertEqual(len(self.svc.list_reports(user("u1", "t1", "viewer"))), 0)
        self.assertEqual(len(self.svc.list_reports(user("u1", "t1", "analyst"))), 0)
        self.assertEqual(len(self.svc.list_reports(user("u1", "t1", "admin"))), 0)


# ---------------------------------------------------------------------------
# 6. audit trail
# ---------------------------------------------------------------------------
class TestAudit(Base):
    def actions(self, object_id=None):
        return [r["action"] for r in self.store.audit_rows(object_id)]

    def test_save_read_list_revoke_are_audited(self):
        actor = user("u1", "t1", "analyst")
        report_id = self.seed_report(actor)
        self.svc.get_report(actor, report_id)
        self.svc.list_reports(actor)
        self.svc.revoke_report(actor, report_id, "done")
        logged = self.actions(report_id)
        for action in ("report.save", "report.read", "report.revoke"):
            self.assertIn(action, logged)
        self.assertIn("report.list", [r["action"] for r in self.store.audit_rows()])

    def test_audit_rows_carry_actor_and_tenant(self):
        actor = user("u1", "t1", "analyst")
        report_id = self.seed_report(actor)
        for row in self.store.audit_rows(report_id):
            self.assertEqual(row["actor_id"], "u1")
            self.assertEqual(row["tenant_id"], "t1")

    def test_batch_writes_are_audited_per_item(self):
        actor = user("u1", "t1", "analyst")
        ids = self.svc.save_batch(actor, [{"name": "a", "payload": {"i": 1}}])["saved"]
        self.assertEqual(len(ids), 1)
        self.assertIn("report.save", self.actions(ids[0]))


# ---------------------------------------------------------------------------
# 7. batch truthfulness
# ---------------------------------------------------------------------------
class TestBatchTruth(Base):
    def test_partial_batch_reports_the_truth(self):
        actor = user("u1", "t1", "analyst")
        result = self.svc.save_batch(
            actor,
            [
                {"name": "ok-1", "payload": {"i": 1}},
                {"name": "   ", "payload": {"i": 2}},  # invalid: empty name
                {"name": "ok-2", "payload": {"i": 3}},
            ],
        )
        self.assertEqual(result["applied"], 2)
        self.assertEqual(len(result["saved"]), 2)
        self.assertNotEqual(result["status"], "complete")
        self.assertEqual(count_reports(self.store, "t1"), 2)

    def test_applied_matches_rows_actually_persisted(self):
        actor = user("u1", "t1", "analyst")
        items = [
            {"name": "a", "payload": {"i": 1}},
            {"payload": {"i": 2}},  # missing name
            "not-an-item",
            {"name": "d", "payload": {"i": 4}},
        ]
        result = self.svc.save_batch(actor, items)
        self.assertEqual(result["applied"], len(result["saved"]))
        self.assertEqual(result["applied"], count_reports(self.store, "t1"))
        self.assertEqual(result["status"], "partial")

    def test_saved_ids_are_all_really_there(self):
        actor = user("u1", "t1", "analyst")
        result = self.svc.save_batch(actor, [{"name": "a", "payload": {"i": 1}}])
        for report_id in result["saved"]:
            self.assertIsNotNone(
                self.store.fetchone("SELECT id FROM reports WHERE id = ?", (report_id,))
            )

    def test_complete_batch_is_reported_complete(self):
        actor = user("u1", "t1", "analyst")
        result = self.svc.save_batch(
            actor, [{"name": "a", "payload": {"i": 1}}, {"name": "b", "payload": {"i": 2}}]
        )
        self.assertEqual(result["applied"], 2)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(count_reports(self.store, "t1"), 2)

    def test_wholly_invalid_batch_saves_nothing_and_says_so(self):
        actor = user("u1", "t1", "analyst")
        result = self.svc.save_batch(actor, [{"name": ""}, {"name": "x", "classification": "bogus"}])
        self.assertEqual(result["applied"], 0)
        self.assertEqual(result["saved"], [])
        self.assertNotEqual(result["status"], "complete")
        self.assertEqual(count_reports(self.store, "t1"), 0)

    def test_batch_cannot_launder_a_cross_tenant_item(self):
        actor = user("u1", "t1", "analyst")
        result = self.svc.save_batch(
            actor, [{"name": "a", "payload": {"tenant_id": "t2"}}]
        )
        self.assertEqual(count_reports(self.store, "t2"), 0)
        self.assertEqual(result["applied"], 1)


# ---------------------------------------------------------------------------
# 8. snapshot immutability / truthful revocation state
# ---------------------------------------------------------------------------
class TestSnapshotAndState(Base):
    def test_revocation_does_not_touch_the_snapshot(self):
        actor = user("u1", "t1", "analyst")
        report_id = self.seed_report(actor, payload={"rows": 7})
        before = self.store.fetchone(
            "SELECT payload_json, content_hash FROM report_snapshots WHERE report_id = ?",
            (report_id,),
        )
        self.svc.revoke_report(actor, report_id, "done")
        after = self.store.fetchone(
            "SELECT payload_json, content_hash FROM report_snapshots WHERE report_id = ?",
            (report_id,),
        )
        self.assertEqual(before["content_hash"], after["content_hash"])
        self.assertEqual(before["payload_json"], after["payload_json"])
        self.assertEqual(self.svc.get_report(actor, report_id)["content_hash"], after["content_hash"])

    def test_list_reports_reports_revocation_truthfully(self):
        actor = user("u1", "t1", "analyst")
        report_id = self.seed_report(actor, name="a")
        self.assertFalse(self.svc.list_reports(actor)[0]["revoked"])
        self.svc.revoke_report(actor, report_id, "done")
        row = [r for r in self.svc.list_reports(actor) if r["id"] == report_id]
        self.assertEqual(len(row), 1)
        self.assertTrue(row[0]["revoked"])

    def test_dataset_feature_still_roundtrips(self):
        registry = DatasetRegistry(self.store)
        actor = user("u1", "t1", "analyst")
        dataset_id = registry.save_dataset(actor, "Sales", {"rows": 3})
        got = registry.get_dataset(actor, dataset_id)
        self.assertEqual(got["payload"], {"rows": 3})
        self.assertEqual(got["tenant_id"], "t1")
        self.assertEqual([d["name"] for d in registry.list_datasets(actor)], ["Sales"])


if __name__ == "__main__":
    unittest.main()
