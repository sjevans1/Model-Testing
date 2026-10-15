"""Mutation harness for the T8 acceptance suite.

Builds a corrected reference copy of SavedReportsService (mutation/ref_service_tail.py) and
applies one seeded defect at a time into a fresh copy of src/ and tests/ under mutation/.
Each mutant must make at least one test fail. The reference (no mutation) must pass.
Writes mutation/results.json. Does not modify the shipped src/ or tests/test_smoke.py.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
MUT = ROOT / "mutation"
TAIL = (MUT / "ref_service_tail.py").read_text()
SVC_ORIG = (ROOT / "src/reportcore/service.py").read_text()
AUTHZ_ORIG = (ROOT / "src/reportcore/authz.py").read_text()

FIX_AUTHZ = (
    "    if actor.role in ROLE_LEVEL and role_level(actor.role) < role_level(minimum):",
    "    if actor.role not in ROLE_LEVEL or role_level(actor.role) < role_level(minimum):",
)


def base_service() -> str:
    head = SVC_ORIG[: SVC_ORIG.index("class SavedReportsService")]
    head = head.replace(
        "from .errors import Conflict, Forbidden, NotFound, ValidationError",
        "from .errors import ReportCoreError, Conflict, Forbidden, NotFound, ValidationError",
    )
    return head + TAIL


def build(name: str, svc_muts=(), authz_muts=()) -> pathlib.Path:
    dst = MUT / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(ROOT / "src", dst / "src")
    shutil.copytree(ROOT / "tests", dst / "tests")
    svc = base_service()
    marker = "class SavedReportsService"
    head, tail_part = svc.split(marker, 1)
    tail_part = marker + tail_part
    for old, new in svc_muts:
        assert tail_part.count(old) == 1, ("service mutation not unique in SavedReportsService", old[:70])
        tail_part = tail_part.replace(old, new)
    svc = head + tail_part
    authz = AUTHZ_ORIG
    authz = authz.replace(FIX_AUTHZ[0], FIX_AUTHZ[1])  # reference is fail-closed
    for old, new in authz_muts:
        assert authz.count(old) == 1, ("authz mutation not unique", old[:70])
        authz = authz.replace(old, new)
    (dst / "src/reportcore/service.py").write_text(svc)
    (dst / "src/reportcore/authz.py").write_text(authz)
    return dst


def run(d: pathlib.Path):
    r = subprocess.run(
        ["python3", "-m", "unittest", "discover", "-s", "tests"],
        cwd=d,
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
    )
    lines = r.stderr.splitlines()
    fails = sorted({ln.split(" (")[0] for ln in lines if ln.startswith(("FAIL:", "ERROR:"))})
    return {"exit": r.returncode, "summary": lines[-1] if lines else "", "failing": fails}


# Each mutant: (id, claim, description, svc_muts, authz_muts)
GET_NO_TENANT = ("        require_tenant(actor, row[\"tenant_id\"])\n        if not may_read_classification(actor, row[\"classification\"]):\n            raise Forbidden(\"classification not readable by this role\")\n        snapshot",
                 "        if not may_read_classification(actor, row[\"classification\"]):\n            raise Forbidden(\"classification not readable by this role\")\n        snapshot")
MUTANTS = [
    ("M1", "claim1", "get_report has no tenant scope (defect D1)",
     [GET_NO_TENANT], []),
    ("M2", "claim1", "get_report ignores classification (defect D3)",
     [("        if not may_read_classification(actor, row[\"classification\"]):\n            raise Forbidden(\"classification not readable by this role\")\n        snapshot", "        snapshot")], []),
    ("M3", "claim1", "get_report reports a foreign tenant as Forbidden, not NotFound (error-oracle)",
     [("        require_tenant(actor, row[\"tenant_id\"])\n        if not may_read_classification",
       "        if row[\"tenant_id\"] != actor.tenant_id:\n            raise Forbidden(\"other tenant\")\n        if not may_read_classification")], []),
    ("M4", "claim1", "revoke_report has no tenant check (defect D2)",
     [("        require_tenant(actor, row[\"tenant_id\"])\n        require_role(actor, \"admin\")\n        with",
       "        require_role(actor, \"admin\")\n        with")], []),
    ("M5", "claim1", "revoke_report has no role check (defect D2)",
     [("        require_tenant(actor, row[\"tenant_id\"])\n        require_role(actor, \"admin\")\n        with",
       "        require_tenant(actor, row[\"tenant_id\"])\n        with")], []),
    ("M6", "claim1", "authz fails open for unknown roles (defect D4)",
     [], [FIX_AUTHZ[::-1]]),
    ("M7", "claim1", "save trusts payload tenant_id over the actor (defect D5)",
     [("        tenant_id = actor.tenant_id\n        report_id",
       "        tenant_id = str(payload.get(\"tenant_id\") or actor.tenant_id)\n        report_id")], []),
    ("M8", "claim1", "list_reports is not tenant scoped (defect D6)",
     [("            \" WHERE tenant_id = ? ORDER BY name\",\n            (actor.tenant_id,),",
       "            \" ORDER BY name\",\n            (),")], []),
    ("M9", "claim1", "list_reports lists revoked reports as active (revoked hard-coded False, filter removed; defect D6)",
     [("                \"revoked\": r[\"revoked_at\"] is not None,\n            }\n            for r in rows",
       "                \"revoked\": False,\n            }\n            for r in rows"),
      ("if may_read_classification(actor, r[\"classification\"]) and r[\"revoked_at\"] is None",
       "if may_read_classification(actor, r[\"classification\"])")], []),
    ("M10", "claim1", "list_reports ignores classification",
     [("if may_read_classification(actor, r[\"classification\"]) and r[\"revoked_at\"] is None",
       "if r[\"revoked_at\"] is None")], []),
    ("M11", "claim1", "viewer can save a report (write gate removed)",
     [("        require_role(actor, \"analyst\")\n        if classification == \"confidential\":\n            require_role(actor, \"admin\")\n        tenant_id",
       "        if classification == \"confidential\":\n            require_role(actor, \"admin\")\n        tenant_id")], []),
    ("M12", "claim1", "unknown classification accepted on save (bypasses confidential gate)",
     [("        classification = _validate_classification(classification)\n        require_role(actor, \"analyst\")",
       "        require_role(actor, \"analyst\")")], []),
    ("M13", "claim2", "revoke rewrites the stored snapshot payload",
     [("        with self.store.conn:\n            self.store.execute(\n                \"UPDATE reports SET revoked_at",
       "        with self.store.conn:\n            self.store.execute(\n                \"UPDATE report_snapshots SET payload_json = ? WHERE report_id = ?\",\n                ('{\"revoked\":true}', report_id),\n            )\n            self.store.execute(\n                \"UPDATE reports SET revoked_at")], []),
    ("M14", "claim2", "revoke recomputes the content hash on the snapshot",
     [("        with self.store.conn:\n            self.store.execute(\n                \"UPDATE reports SET revoked_at",
       "        with self.store.conn:\n            self.store.execute(\n                \"UPDATE report_snapshots SET content_hash = 'deadbeef' WHERE report_id = ?\",\n                (report_id,),\n            )\n            self.store.execute(\n                \"UPDATE reports SET revoked_at")], []),
    ("M15", "claim2", "revoke deletes the snapshot row",
     [("        with self.store.conn:\n            self.store.execute(\n                \"UPDATE reports SET revoked_at",
       "        with self.store.conn:\n            self.store.execute(\"DELETE FROM report_snapshots WHERE report_id = ?\", (report_id,))\n            self.store.execute(\n                \"UPDATE reports SET revoked_at")], []),
    ("M16", "claim2", "revoke changes the report name (non-status column edited)",
     [("\"UPDATE reports SET revoked_at = ?, revoked_by = ?, revoke_reason = ?\"",
       "\"UPDATE reports SET name = name || ' (revoked)', revoked_at = ?, revoked_by = ?, revoke_reason = ?\"")], []),
    ("M17", "claim3", "batch always reports status complete (defect D8)",
     [("        status = \"complete\" if failed == 0 else \"partial\"",
       "        status = \"complete\"")], []),
    ("M18", "claim3", "batch applied counts requested items, not saved (defect D8)",
     [("        return {\"applied\": len(saved), \"saved\": saved, \"status\": status}",
       "        return {\"applied\": len(items), \"saved\": saved, \"status\": status}")], []),
    ("M19", "claim3", "batch status complete when any item saved",
     [("        status = \"complete\" if failed == 0 else \"partial\"",
       "        status = \"complete\" if saved else \"partial\"")], []),
    ("M20", "claim3", "batch swallows failures and does not report them (no partial status)",
     [("        status = \"complete\" if failed == 0 else \"partial\"",
       "        status = \"complete\"\n        failed = 0")], []),
]

# Reference must pass first.
ref = build("ref")
ref_result = run(ref)
results = {"reference": ref_result, "mutants": []}
print("reference:", ref_result["exit"], ref_result["summary"], ref_result["failing"])

for mid, claim, desc, svc_muts, authz_muts in MUTANTS:
    d = build(mid, svc_muts=svc_muts, authz_muts=authz_muts)
    res = run(d)
    detected = res["exit"] != 0
    results["mutants"].append({"id": mid, "claim": claim, "desc": desc, "detected": detected, **res})
    print(f"{mid:4} {claim} detected={detected} {res['summary']}  <- {desc}")

(MUT / "results.json").write_text(json.dumps(results, indent=2))
