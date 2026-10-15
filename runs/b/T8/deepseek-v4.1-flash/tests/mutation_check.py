#!/usr/bin/env python3
"""Mutation evidence for the SavedReports acceptance suite (T8).

This file is a tool, not a test: ``test*.py`` discovery ignores it, and it never imports
``reportcore`` itself.  It answers two questions the suite on its own cannot:

  1. Is every test satisfiable?  It applies a *repair* of the seeded defects to a scratch
     copy and requires the suite to go green there (a test that even a correct
     implementation fails is a broken test).
  2. Does every test actually bite?  On top of the repaired copy it re-introduces one
     defect at a time and requires the named test(s) to fail.

Run:   python3 tests/mutation_check.py            # whole matrix
       python3 tests/mutation_check.py --only M8
       python3 tests/mutation_check.py --keep      # keep the scratch trees

Each case runs the official command in its own copy of the tree:
    PYTHONPATH=src python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
SERVICE = "src/reportcore/service.py"
AUTHZ = "src/reportcore/authz.py"
STORE = "src/reportcore/store.py"

# ---------------------------------------------------------------------------------------
# The repair: every seeded defect in the shipped tree, fixed exactly once, so that the
# suite has a reference implementation whose contract the tests describe.
# ---------------------------------------------------------------------------------------

REPAIR = [
    (
        SERVICE,
        """        name = _validate_name(name)
        payload = _validate_payload(payload)
        # DEFECT D5: trusts a client-supplied tenant id over the authenticated actor.
        tenant_id = str(payload.get("tenant_id") or actor.tenant_id)
""",
        """        name = _validate_name(name)
        payload = _validate_payload(payload)
        classification = _validate_classification(classification)
        require_role(actor, "analyst")
        if classification == "confidential":
            require_role(actor, "admin")
        tenant_id = actor.tenant_id
""",
    ),
    (
        SERVICE,
        """        # DEFECT D1: no tenant scope on the read.
        row = self.store.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))
        if row is None:
            raise NotFound("no such object")
        snapshot = self.store.fetchone(
            "SELECT * FROM report_snapshots WHERE report_id = ?", (report_id,)
        )
        if snapshot is None:
            raise NotFound("no such object")
        # DEFECT D3: classification is never consulted.
""",
        """        row = self.store.fetchone(
            "SELECT * FROM reports WHERE id = ? AND tenant_id = ?", (report_id, actor.tenant_id)
        )
        if row is None:
            raise NotFound("no such object")
        if not may_read_classification(actor, row["classification"]):
            raise Forbidden("classification not readable by this role")
        snapshot = self.store.fetchone(
            "SELECT * FROM report_snapshots WHERE report_id = ?", (report_id,)
        )
        if snapshot is None:
            raise NotFound("no such object")
""",
    ),
    (
        SERVICE,
        """        rows = self.store.fetchall(
            "SELECT id, tenant_id, owner_id, name, classification, revoked_at FROM reports"
            " ORDER BY name"
        )
        # DEFECT D6: lists every tenant, and revoked rows leak as "saved" entries.
        out = [
            {
                "id": r["id"],
                "name": r["name"],
                "classification": r["classification"],
                "owner_id": r["owner_id"],
                "revoked": False,
            }
            for r in rows
        ]
""",
        """        rows = self.store.fetchall(
            "SELECT id, tenant_id, owner_id, name, classification, revoked_at FROM reports"
            " WHERE tenant_id = ? ORDER BY name",
            (actor.tenant_id,),
        )
        out = [
            {
                "id": r["id"],
                "name": r["name"],
                "classification": r["classification"],
                "owner_id": r["owner_id"],
                "revoked": r["revoked_at"] is not None,
            }
            for r in rows
            if may_read_classification(actor, r["classification"])
        ]
""",
    ),
    (
        SERVICE,
        """        # DEFECT D2: exists-by-id only. No tenant check, no role check.
        row = self.store.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))
        if row is None:
            raise NotFound("no such object")
""",
        """        row = self.store.fetchone(
            "SELECT * FROM reports WHERE id = ? AND tenant_id = ?", (report_id, actor.tenant_id)
        )
        if row is None:
            raise NotFound("no such object")
        require_role(actor, "admin")
""",
    ),
    (
        SERVICE,
        "from .errors import Conflict, Forbidden, NotFound, ValidationError\n",
        "from .errors import Conflict, Forbidden, NotFound, ReportCoreError, ValidationError\n",
    ),
    (
        SERVICE,
        """        saved = []
        for item in items:
            try:
                saved.append(
                    self.save_report(
                        actor,
                        (item or {}).get("name", ""),
                        (item or {}).get("payload") or {},
                        (item or {}).get("classification", "internal"),
                    )
                )
            except Exception:  # noqa: BLE001
                # DEFECT D8: per-item failures are swallowed, and the batch always
                # reports itself complete with the requested item count.
                pass
        return {"applied": len(items), "saved": saved, "status": "complete"}
""",
        """        saved = []
        failed = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                failed.append({"index": index, "error": "ValidationError"})
                continue
            try:
                saved.append(
                    self.save_report(
                        actor,
                        item.get("name", ""),
                        item.get("payload") or {},
                        item.get("classification", "internal"),
                    )
                )
            except ReportCoreError as exc:
                failed.append({"index": index, "error": type(exc).__name__})
        return {
            "applied": len(saved),
            "saved": saved,
            "failed": failed,
            "status": "complete" if not failed else "partial",
        }
""",
    ),
    (
        AUTHZ,
        """    # DEFECT D4: only roles we recognise are enforced, so an unknown role fails open.
    if actor.role in ROLE_LEVEL and role_level(actor.role) < role_level(minimum):
""",
        """    if role_level(actor.role) < role_level(minimum):
""",
    ),
]

# ---------------------------------------------------------------------------------------
# Mutations: one seeded defect each, applied on top of the repaired tree.
# ---------------------------------------------------------------------------------------

def mutation(name, patches, *expect):
    return {"name": name, "patches": patches, "expect": list(expect), "base": "repair"}


MUTATIONS = [
    mutation(
        "M1_get_report_without_tenant_scope",
        [(SERVICE,
          """        row = self.store.fetchone(
            "SELECT * FROM reports WHERE id = ? AND tenant_id = ?", (report_id, actor.tenant_id)
        )
        if row is None:
            raise NotFound("no such object")
        if not may_read_classification(actor, row["classification"]):
""",
          """        row = self.store.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))
        if row is None:
            raise NotFound("no such object")
        if not may_read_classification(actor, row["classification"]):
""")],
        "test_foreign_tenant_member_cannot_read_the_report",
        "test_read_surface_never_surfaces_a_foreign_report",
    ),
    mutation(
        "M2_get_report_ignores_classification",
        [(SERVICE,
          """        if not may_read_classification(actor, row["classification"]):
            raise Forbidden("classification not readable by this role")
        snapshot = self.store.fetchone(
""",
          """        snapshot = self.store.fetchone(
""")],
        "test_confidential_report_is_readable_only_by_tenant_admins",
    ),
    mutation(
        "M3_revoke_without_role_check",
        [(SERVICE,
          """            raise NotFound("no such object")
        require_role(actor, "admin")
        with self.store.conn:
""",
          """            raise NotFound("no such object")
        with self.store.conn:
""")],
        "test_revoke_requires_an_admin_role",
    ),
    mutation(
        "M4_revoke_without_tenant_scope",
        [(SERVICE,
          """        row = self.store.fetchone(
            "SELECT * FROM reports WHERE id = ? AND tenant_id = ?", (report_id, actor.tenant_id)
        )
        if row is None:
            raise NotFound("no such object")
        require_role(actor, "admin")
""",
          """        row = self.store.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))
        if row is None:
            raise NotFound("no such object")
        require_role(actor, "admin")
""")],
        "test_foreign_tenant_cannot_revoke_and_existence_is_not_disclosed",
    ),
    mutation(
        "M5_payload_decides_tenant",
        [(SERVICE,
          "        tenant_id = actor.tenant_id\n",
          "        tenant_id = str(payload.get(\"tenant_id\") or actor.tenant_id)\n")],
        "test_payload_tenant_id_cannot_move_a_report",
        "test_payload_tenant_id_cannot_forge_the_audit_tenant",
    ),
    mutation(
        "M6_list_reports_not_scoped",
        [(SERVICE,
          """            "SELECT id, tenant_id, owner_id, name, classification, revoked_at FROM reports"
            " WHERE tenant_id = ? ORDER BY name",
            (actor.tenant_id,),
        )
""",
          """            "SELECT id, tenant_id, owner_id, name, classification, revoked_at FROM reports"
            " ORDER BY name"
        )
""")],
        "test_list_reports_is_tenant_scoped",
    ),
    mutation(
        "M7_list_reports_hardcodes_not_revoked",
        [(SERVICE,
          """                "revoked": r["revoked_at"] is not None,
""",
          """                "revoked": False,
""")],
        "test_list_reports_reports_revocation_state_truthfully",
    ),
    mutation(
        "M8_batch_swallows_failures",
        [(SERVICE,
          """            except ReportCoreError as exc:
                failed.append({"index": index, "error": type(exc).__name__})
        return {
            "applied": len(saved),
            "saved": saved,
            "failed": failed,
            "status": "complete" if not failed else "partial",
        }
""",
          """            except ReportCoreError:
                pass
        return {"applied": len(items), "saved": saved, "status": "complete"}
""")],
        "test_partial_batch_is_not_reported_as_complete",
        "test_partial_batch_count_equals_what_was_actually_saved",
        "test_mixed_malformed_and_valid_batch_reports_partial_truthfully",
        "test_batch_of_only_invalid_items_never_reports_them_as_saved",
    ),
    mutation(
        "M9_unknown_role_fails_open",
        [(AUTHZ,
          "    if role_level(actor.role) < role_level(minimum):\n",
          "    if actor.role in ROLE_LEVEL and role_level(actor.role) < role_level(minimum):\n")],
        "test_unknown_role_fails_closed_everywhere",
    ),
    mutation(
        "M10_save_without_role_gate",
        [(SERVICE,
          """        classification = _validate_classification(classification)
        require_role(actor, "analyst")
        if classification == "confidential":
            require_role(actor, "admin")
        tenant_id = actor.tenant_id
""",
          """        classification = _validate_classification(classification)
        tenant_id = actor.tenant_id
""")],
        "test_saving_requires_at_least_analyst",
        "test_creating_a_confidential_report_requires_an_admin",
        "test_batch_requires_authorisation_like_a_single_save",
    ),
    mutation(
        "M11_save_does_not_validate_classification",
        [(SERVICE,
          """        classification = _validate_classification(classification)
        require_role(actor, "analyst")
        if classification == "confidential":
            require_role(actor, "admin")
        tenant_id = actor.tenant_id
""",
          """        require_role(actor, "analyst")
        if classification == "confidential":
            require_role(actor, "admin")
        tenant_id = actor.tenant_id
""")],
        "test_classification_must_be_a_known_value",
    ),
    mutation(
        "M12_revoke_rewrites_the_snapshot",
        [(SERVICE,
          """            self.store.add_audit(actor.id, "report.revoke", "report", report_id, row["tenant_id"])
""",
          """            self.store.execute(
                "UPDATE report_snapshots SET payload_json = ? WHERE report_id = ?",
                ('{"redacted":true}', report_id),
            )
            self.store.add_audit(actor.id, "report.revoke", "report", report_id, row["tenant_id"])
""")],
        "test_revoke_leaves_the_stored_snapshot_byte_identical",
        "test_revocation_does_not_change_the_stored_payload_bytes",
    ),
    mutation(
        "M13_revoke_by_content_hash",
        [(SERVICE,
          """                "UPDATE reports SET revoked_at = ?, revoked_by = ?, revoke_reason = ?"
                " WHERE id = ?",
""",
          """                "UPDATE reports SET revoked_at = ?, revoked_by = ?, revoke_reason = ?"
                " WHERE id IN (SELECT r.id FROM reports r JOIN report_snapshots s"
                " ON s.report_id = r.id WHERE s.content_hash ="
                " (SELECT content_hash FROM report_snapshots WHERE report_id = ?))",
""")],
        "test_snapshot_is_not_aliased_between_two_reports_with_equal_content",
        "test_duplicate_submission_does_not_share_revocation_state",
    ),
    mutation(
        "M14_non_canonical_content_hash",
        [(SERVICE,
          """    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
""",
          """    blob = json.dumps(payload, separators=(",", ":"), default=str)
""")],
        "test_equal_payloads_hash_equal_whatever_the_key_order",
        "test_save_stores_canonical_json_and_matching_sha256",
    ),
    mutation(
        "M15_revoke_deletes_the_snapshot",
        [(SERVICE,
          """            self.store.add_audit(actor.id, "report.revoke", "report", report_id, row["tenant_id"])
""",
          """            self.store.execute("DELETE FROM report_snapshots WHERE report_id = ?", (report_id,))
            self.store.add_audit(actor.id, "report.revoke", "report", report_id, row["tenant_id"])
""")],
        "test_revoke_neither_deletes_nor_duplicates_the_snapshot",
        "test_revoked_report_is_still_readable_to_the_owning_tenant",
    ),
    mutation(
        "M16_store_shares_one_connection_per_path",
        [(STORE,
          """    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
""",
          """    def __init__(self, path: str = ":memory:") -> None:
        self._conn = _shared_conn(path)
"""),
         (STORE,
          """class Store:
    \"\"\"Thin wrapper over sqlite3 with the schema applied.\"\"\"
""",
          """_SHARED_CONNECTIONS: dict = {}


def _shared_conn(path: str):
    \"\"\"Seeded defect: hand out one connection per path, shared across threads.\"\"\"
    if path == ":memory:":
        return sqlite3.connect(path)
    if path not in _SHARED_CONNECTIONS:
        _SHARED_CONNECTIONS[path] = sqlite3.connect(path)
    return _SHARED_CONNECTIONS[path]


class Store:
    \"\"\"Thin wrapper over sqlite3 with the schema applied.\"\"\"
""")],
        "test_concurrent_revocations_and_reads_leave_a_consistent_report",
    ),
    mutation(
        "M17_privileged_read_not_audited",
        [(SERVICE,
          """        self.store.add_audit(actor.id, "report.read", "report", report_id, row["tenant_id"])
""",
          """        pass  # seeded defect: no audit row for a privileged read
""")],
        "test_privileged_read_is_audited_against_the_owning_tenant",
    ),
    mutation(
        "M18_list_reports_ignores_classification",
        [(SERVICE,
          """            for r in rows
            if may_read_classification(actor, r["classification"])
        ]
""",
          """            for r in rows
        ]
""")],
        "test_list_reports_hides_confidential_from_non_admins",
    ),
]

# The suite must fail on the shipped tree for exactly these reasons; this is the same
# evidence as running discover in the repo, pinned so that a silent "everything passes"
# regression in the suite is caught by the harness itself.
SHIPPED_EXPECT = [
    "test_foreign_tenant_member_cannot_read_the_report",
    "test_foreign_tenant_confidential_read_is_not_found_not_forbidden",
    "test_read_surface_never_surfaces_a_foreign_report",
    "test_confidential_report_is_readable_only_by_tenant_admins",
    "test_list_reports_is_tenant_scoped",
    "test_list_reports_hides_confidential_from_non_admins",
    "test_payload_tenant_id_cannot_move_a_report",
    "test_payload_tenant_id_cannot_forge_the_audit_tenant",
    "test_revoke_requires_an_admin_role",
    "test_foreign_tenant_cannot_revoke_and_existence_is_not_disclosed",
    "test_list_reports_reports_revocation_state_truthfully",
    "test_partial_batch_is_not_reported_as_complete",
    "test_partial_batch_count_equals_what_was_actually_saved",
    "test_batch_of_only_invalid_items_never_reports_them_as_saved",
    "test_batch_with_a_malformed_item_never_over_reports",
    "test_batch_item_cannot_grant_itself_a_higher_classification",
    "test_batch_items_cannot_choose_their_tenant",
    "test_batch_requires_authorisation_like_a_single_save",
    "test_saving_requires_at_least_analyst",
    "test_creating_a_confidential_report_requires_an_admin",
    "test_unknown_role_fails_closed_everywhere",
    "test_role_change_is_respected_on_the_next_call",
    "test_a_demoted_admin_can_no_longer_read_confidential_reports",
    "test_classification_must_be_a_known_value",
]

BLOCK = re.compile(r"^(FAIL|ERROR): (\S+) \((.+?)\)", re.M)


def apply_patch(root: pathlib.Path, rel: str, old: str, new: str, label: str) -> None:
    path = root / rel
    text = path.read_text()
    occurrences = text.count(old)
    if occurrences != 1:
        raise SystemExit(
            f"[{label}] patch anchor matched {occurrences} times (expected exactly 1) in {rel}; "
            "the harness refuses to run a patch that would silently do nothing"
        )
    path.write_text(text.replace(old, new))


def run_suite(root: pathlib.Path):
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = "src"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=root, env=env, capture_output=True, text=True, timeout=900,
    )
    output = proc.stdout + proc.stderr
    ran = re.search(r"^Ran (\d+) tests", output, re.M)
    failures = sorted({match[2] for match in BLOCK.findall(output)})
    return {
        "returncode": proc.returncode,
        "ran": int(ran.group(1)) if ran else None,
        "failures": failures,
        "methods": sorted({f.rsplit(".", 1)[-1] for f in failures}),
        "output": output,
    }


def build(root: pathlib.Path, case: dict) -> None:
    if case["base"] == "repair":
        for rel, old, new in REPAIR:
            apply_patch(root, rel, old, new, f"{case['name']}:repair")
    for rel, old, new in case["patches"]:
        apply_patch(root, rel, old, new, case["name"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", default=[], help="run only these cases (substring match)")
    parser.add_argument("--keep", action="store_true", help="keep the scratch trees")
    args = parser.parse_args()

    cases = [{"name": "SHIPPED", "base": "none", "patches": [], "expect": SHIPPED_EXPECT,
              "expect_clean": False}] + MUTATIONS
    cases.append({"name": "REPAIRED", "base": "repair", "patches": [], "expect": [],
                  "expect_clean": True})
    if args.only:
        cases = [c for c in cases if any(token in c["name"] for token in args.only)]

    workroot = pathlib.Path(tempfile.mkdtemp(prefix="t8-mutation-"))
    print(f"scratch: {workroot}\n")
    bad = 0
    for case in cases:
        dest = workroot / case["name"]
        dest.mkdir()
        shutil.copytree(
            REPO, dest / "repo",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "*.sqlite3"),
        )
        repo_copy = dest / "repo"
        build(repo_copy, case)
        result = run_suite(repo_copy)
        (dest / "run.log").write_text(result["output"])

        methods = result["methods"]
        if case.get("expect_clean"):
            good = not methods
            detail = f"{result['ran']} tests ran, {len(methods)} failing"
        else:
            missing = [e for e in case["expect"] if not any(e in m for m in methods)]
            good = not missing
            detail = f"{len(methods)} killed of {result['ran']} ran"
            if missing:
                detail += f"; MISSED {missing}"
        bad += 0 if good else 1
        print(f"{'PASS' if good else 'FAIL'}  {case['name']:<48} {detail}")
        if methods and not case.get("expect_clean"):
            for method in methods:
                print(f"          - {method}")
        if not args.keep:
            shutil.rmtree(dest, ignore_errors=True)

    if not args.keep:
        shutil.rmtree(workroot, ignore_errors=True)
    print(f"\n{cases.__len__()} cases, {bad} failed expectations")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
