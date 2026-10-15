"""CLAIM 1 (permission safety).

CLAIMS.md: "Saved reports are permission safe: a report and its snapshot are readable only
by members of the owning tenant, and confidential reports only by tenant admins. A caller
cannot move a report into another tenant by supplying a tenant id."

Each test below fails on an implementation that breaks its clause:
  * cross-tenant reads succeed            -> test_foreign_tenant_* / test_read_surface_*
  * confidential readable below admin     -> test_confidential_report_*
  * payload decides tenancy               -> test_payload_tenant_id_*
  * list_reports leaks other tenants      -> test_list_reports_*
"""
from __future__ import annotations

from reportcore import Forbidden, NotFound

from support import (
    SavedReportsCase,
    content_hash,
    count,
    read_surface,
    report_row,
    surfaces,
)


class Claim1Permissions(SavedReportsCase):

    # ---------------------------------------------------------------- normal operations

    def test_owner_tenant_member_roundtrips_the_report(self):
        """Baseline: a tenant member saves and reads back exactly what they stored."""
        payload = {"rows": 3, "cols": 2, "title": "Q3"}
        report_id = self.save(self.t1_analyst, "Q3 revenue", payload)

        self.assertIsInstance(report_id, str)
        self.assertTrue(report_id, "save_report must return an identifier")

        got = self.svc.get_report(self.t1_analyst, report_id)
        self.assertEqual(got["id"], report_id)
        self.assertEqual(got["payload"], payload)
        self.assertEqual(got["tenant_id"], "t1")
        self.assertEqual(got["owner_id"], self.t1_analyst.id)
        self.assertEqual(got["name"], "Q3 revenue")
        self.assertEqual(got["classification"], "internal")
        self.assertFalse(got["revoked"])
        self.assertEqual(got["content_hash"], content_hash(payload))

    def test_same_tenant_viewer_may_read_an_internal_report(self):
        """Internal reports are tenant-readable regardless of role."""
        report_id = self.save(self.t1_analyst, "Internal")
        self.assertEqual(self.svc.get_report(self.t1_viewer, report_id)["payload"], {"rows": 1})

    def test_privileged_read_is_audited_against_the_owning_tenant(self):
        report_id = self.save(self.t1_analyst, "Audited")
        self.svc.get_report(self.t1_analyst, report_id)
        rows = [r for r in self.store.audit_rows(report_id) if r["action"] == "report.read"]
        self.assertEqual(len(rows), 1, "a privileged read must leave exactly one audit row")
        self.assertEqual(rows[0]["actor_id"], self.t1_analyst.id)
        self.assertEqual(rows[0]["tenant_id"], "t1")

    # ------------------------------------------------------------ cross-tenant access

    def test_foreign_tenant_member_cannot_read_the_report(self):
        """A report is readable only by members of the owning tenant."""
        report_id = self.save(self.t1_analyst, "T1 internal", {"secret": "t1-only"})

        with self.assertRaises(NotFound):
            self.svc.get_report(self.t2_admin, report_id)
        with self.assertRaises(NotFound):
            self.svc.get_report(self.t2_viewer, report_id)

    def test_foreign_tenant_error_does_not_disclose_existence(self):
        """Convention: a foreign tenant is a NotFound, never a Forbidden (README rule 3)."""
        report_id = self.save(self.t1_analyst, "T1 internal")
        missing_id = "0" * 32

        with self.assertRaises(NotFound) as existing:
            self.svc.get_report(self.t2_admin, report_id)
        with self.assertRaises(NotFound) as absent:
            self.svc.get_report(self.t2_admin, missing_id)

        self.assertIs(type(existing.exception), type(absent.exception))
        self.assertNotIn(report_id, str(existing.exception))

    def test_foreign_tenant_confidential_read_is_not_found_not_forbidden(self):
        """Tenant scoping is applied before classification, so existence still never leaks."""
        report_id = self.save(self.t1_admin, "T1 confidential", {"n": 1}, "confidential")
        with self.assertRaises(NotFound):
            self.svc.get_report(self.t2_admin, report_id)

    def test_read_surface_never_surfaces_a_foreign_report(self):
        """Sweep every public read entry point, with a positive control so the sweep bites."""
        report_id = self.save(self.t1_analyst, "T1 only")

        mine = surfaces(read_surface(self.svc, self.t1_analyst, report_id), report_id)
        self.assertTrue(
            mine,
            "positive control failed: the owning tenant must see its own report through some "
            "public read entry point, otherwise this sweep proves nothing",
        )

        for foreign in (self.t2_admin, self.t2_analyst, self.t2_viewer):
            leaked = surfaces(read_surface(self.svc, foreign, report_id), report_id)
            self.assertEqual(leaked, [], f"{foreign.id} (tenant {foreign.tenant_id}) saw a foreign report")

    # ------------------------------------------------------------------ confidentiality

    def test_confidential_report_is_readable_only_by_tenant_admins(self):
        """Confidential reports are admin-only, even inside the owning tenant."""
        report_id = self.save(self.t1_admin, "Board pack", {"n": 1}, "confidential")

        for actor in (self.t1_viewer, self.t1_analyst):
            with self.assertRaises(Forbidden):
                self.svc.get_report(actor, report_id)

        self.assertEqual(self.svc.get_report(self.t1_admin, report_id)["payload"], {"n": 1})

    # ------------------------------------------------------- tenant id supplied by caller

    def test_payload_tenant_id_cannot_move_a_report(self):
        """Caller-controlled payloads must not decide tenancy (README rule 6)."""
        report_id = self.save(self.t1_analyst, "Sneaky", {"tenant_id": "t2", "rows": 5})

        self.assertEqual(report_row(self.store, report_id)["tenant_id"], "t1")
        self.assertEqual(self.svc.get_report(self.t1_analyst, report_id)["tenant_id"], "t1")

        with self.assertRaises(NotFound):
            self.svc.get_report(self.t2_admin, report_id)
        self.assertNotIn(report_id, [r["id"] for r in self.svc.list_reports(self.t2_admin)])

    def test_payload_tenant_id_cannot_forge_the_audit_tenant(self):
        report_id = self.save(self.t1_analyst, "Sneaky", {"tenant_id": "t2", "rows": 5})
        rows = [r for r in self.store.audit_rows(report_id) if r["action"] == "report.save"]
        self.assertEqual([r["tenant_id"] for r in rows], ["t1"])

    # -------------------------------------------------------------------------- listing

    def test_list_reports_is_tenant_scoped(self):
        t1_id = self.save(self.t1_analyst, "T1 report")
        t2_id = self.save(self.t2_analyst, "T2 report")

        self.assertEqual([r["id"] for r in self.svc.list_reports(self.t1_analyst)], [t1_id])
        self.assertEqual([r["id"] for r in self.svc.list_reports(self.t2_admin)], [t2_id])

    def test_list_reports_hides_confidential_from_non_admins(self):
        internal_id = self.save(self.t1_analyst, "Internal", classification="internal")
        confidential_id = self.save(self.t1_admin, "Confidential", classification="confidential")

        visible_to_viewer = [r["id"] for r in self.svc.list_reports(self.t1_viewer)]
        self.assertIn(internal_id, visible_to_viewer)
        self.assertNotIn(confidential_id, visible_to_viewer)

        self.assertIn(confidential_id, [r["id"] for r in self.svc.list_reports(self.t1_admin)])

    def test_list_reports_does_not_leak_payloads(self):
        """The list view is metadata only; snapshot content stays behind get_report."""
        self.save(self.t1_analyst, "T1", {"secret": "payload-marker"})
        rendered = repr(self.svc.list_reports(self.t1_analyst))
        self.assertNotIn("payload-marker", rendered)

    def test_listing_is_audited(self):
        self.save(self.t1_analyst, "T1")
        self.svc.list_reports(self.t1_analyst)
        list_audits = [r for r in self.store.audit_rows() if r["action"] == "report.list"]
        self.assertEqual(len(list_audits), 1)
        self.assertEqual(list_audits[0]["tenant_id"], "t1")

    # ------------------------------------------------------------------ guard: no writes

    def test_denied_read_does_not_write_to_the_store(self):
        report_id = self.save(self.t1_analyst, "T1")
        before = (count(self.store, "reports"), count(self.store, "report_snapshots"))
        with self.assertRaises(NotFound):
            self.svc.get_report(self.t2_admin, report_id)
        self.assertEqual((count(self.store, "reports"), count(self.store, "report_snapshots")), before)
