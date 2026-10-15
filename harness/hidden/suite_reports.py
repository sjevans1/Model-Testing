#!/usr/bin/env python3
"""Hidden acceptance suite for the reportcore fixture family (BENCH-MODEL-001).

    python3 suite_reports.py <tree>            # JSON result for every check
    python3 suite_reports.py <tree> --pretty    # human-readable

`tree` is any tree laid out like fixtures/reportcore_t3 (src/reportcore/...).
Never copied into a candidate tree; the harness runs it against a copy.

Each check returns (id, weight_group, passed, detail). The same suite grades:
  T3  - "all checks pass" after the candidate implements SavedReportsService
  T5  - each failing check names a seeded defect that is still present
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import traceback

CHECKS: list[tuple[str, str, str]] = [
    # id, group, description
    ("A01", "core", "save_report returns an id and persists a snapshot with a matching sha256"),
    ("A02", "core", "snapshot payload and content hash are unchanged after revocation"),
    ("A03", "isolation", "get_report for a foreign tenant raises NotFound and returns no data"),
    ("A04", "isolation", "revoke_report on a foreign-tenant report raises NotFound and is a no-op"),
    ("A05", "isolation", "list_reports returns only this tenant's, non-revoked reports"),
    ("A06", "audit", "audit rows are written for save, read, revoke with the actor id"),
    ("A07", "validation", "ValidationError for empty name, non-dict payload, bad classification"),
    ("A08", "classification", "confidential: admin-only to save and read; analyst is refused"),
    ("A09", "roles", "viewer cannot save; Forbidden (not a 500)"),
    ("A10", "failclosed", "an unknown/empty role is denied everywhere (fail closed)"),
    ("A11", "regression", "DatasetRegistry still round-trips and still scopes by tenant"),
    ("A12", "isolation", "a payload-supplied tenant_id cannot move a report to another tenant"),
    ("A13", "batch", "save_batch reports the true saved count and only calls a clean batch complete"),
    ("A14", "revocation", "a revoked report is absent from listings, or clearly marked as revoked"),
]


def _load(tree: pathlib.Path):
    src = str(tree / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    import reportcore  # noqa: WPS433

    return reportcore


def run(tree: pathlib.Path) -> list[dict]:
    import importlib

    results: list[dict] = []

    def record(cid: str, group: str, desc: str, fn) -> None:
        try:
            detail = fn()
            results.append({"id": cid, "group": group, "passed": True,
                            "detail": "ok" if detail is None else detail,
                            "not_applicable": detail is None})
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "id": cid,
                    "group": group,
                    "passed": False,
                    "detail": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc(limit=3).splitlines()[-3:],
                }
            )

    importlib.invalidate_caches()
    try:
        rc = _load(tree)
    except Exception as exc:  # noqa: BLE001
        return [
            {"id": cid, "group": g, "passed": False, "detail": f"import failed: {exc}"}
            for cid, g, _ in CHECKS
        ]

    Store, User = rc.Store, rc.User
    Saved, Datasets = rc.SavedReportsService, rc.DatasetRegistry
    NotFound, Forbidden, ValidationError = rc.NotFound, rc.Forbidden, rc.ValidationError
    Forbidden = rc.Forbidden

    def fresh():
        store = Store()
        store.seed_tenant("t1", "Tenant One")
        store.seed_tenant("t2", "Tenant Two")
        users = {
            "admin1": User(id="admin1", tenant_id="t1", email="admin1@t1", role="admin"),
            "analyst1": User(id="analyst1", tenant_id="t1", email="analyst1@t1", role="analyst"),
            "viewer1": User(id="viewer1", tenant_id="t1", email="viewer1@t1", role="viewer"),
            "admin2": User(id="admin2", tenant_id="t2", email="admin2@t2", role="admin"),
            "ghost": User(id="ghost", tenant_id="t1", email="ghost@t1", role="ghost"),
        }
        return store, users, Saved(store), Datasets(store)

    ctx: dict = {}

    # -- A01 -------------------------------------------------------------------------
    def a01():
        store, u, svc, _ = fresh()
        rid = svc.save_report(u["analyst1"], "Q3", {"total": 42, "rows": [1, 2]})
        assert isinstance(rid, str) and rid, "save_report must return a non-empty id"
        row = store.fetchone("SELECT * FROM report_snapshots WHERE report_id = ?", (rid,))
        assert row is not None, "no snapshot row was written"
        payload = json.loads(row["payload_json"])
        assert payload == {"total": 42, "rows": [1, 2]}, f"payload mismatch: {payload}"
        assert row["content_hash"] and len(row["content_hash"]) == 64, "content_hash is not a sha256"
        ctx["rid"] = rid
        ctx["store"] = store
        ctx["users"] = u
        return f"id={rid[:8]}… hash={row['content_hash'][:12]}…"

    # -- A02 -------------------------------------------------------------------------
    def a02():
        store, u, svc, _ = fresh()
        rid = svc.save_report(u["analyst1"], "Q3", {"total": 42})
        before = store.fetchone("SELECT * FROM report_snapshots WHERE report_id = ?", (rid,))
        svc.revoke_report(u["analyst1"], rid, "superseded")
        after = store.fetchone("SELECT * FROM report_snapshots WHERE report_id = ?", (rid,))
        assert after is not None, "revocation deleted the snapshot"
        assert after["payload_json"] == before["payload_json"], "revocation rewrote snapshot content"
        assert after["content_hash"] == before["content_hash"], "revocation changed the content hash"
        return "snapshot byte-identical after revoke"

    # -- A03 -------------------------------------------------------------------------
    def a03():
        store, u, svc, _ = fresh()
        rid = svc.save_report(u["admin1"] if False else u["analyst1"], "Secret", {"x": 1})
        try:
            got = svc.get_report(u["admin2"], rid)
        except NotFound:
            return "foreign tenant -> NotFound"
        except Forbidden:
            raise AssertionError(
                "cross-tenant read raised Forbidden: that discloses the object exists"
            )
        raise AssertionError(f"cross-tenant read returned data: {got}")

    # -- A04 -------------------------------------------------------------------------
    def a04():
        store, u, svc, _ = fresh()
        rid = svc.save_report(u["analyst1"], "Q3", {"x": 1})
        try:
            svc.revoke_report(u["admin2"], rid, "hostile")
        except NotFound:
            pass
        else:
            raise AssertionError("foreign tenant revoked another tenant's report")
        row = store.fetchone("SELECT revoked_at FROM reports WHERE id = ?", (rid,))
        assert row["revoked_at"] is None, "report was revoked despite the rejection"
        return "foreign revoke refused, state untouched"

    # -- A05 -------------------------------------------------------------------------
    def a05():
        store, u, svc, _ = fresh()
        mine = svc.save_report(u["analyst1"], "Mine", {"x": 1})
        theirs = svc.save_report(u["admin2"], "Theirs", {"x": 2})
        gone = svc.save_report(u["analyst1"], "Old", {"x": 3})
        svc.revoke_report(u["analyst1"], gone, "obsolete")
        rows = svc.list_reports(u["analyst1"])
        ids = {r["id"] for r in rows}
        assert mine in ids, "own report missing from list"
        assert theirs not in ids, "another tenant's report leaked into the list"
        for row in rows:
            if row.get("id") == gone:
                live = (row.get("revoked") is False and not row.get("revoked_at")
                        and str(row.get("status", "")).lower() not in ("revoked", "deleted"))
                assert not live, f"a revoked report is presented as live: {row}"
        return f"visible ids={sorted(i[:6] for i in ids)}"

    # -- A06 -------------------------------------------------------------------------
    def a06():
        store, u, svc, _ = fresh()
        rid = svc.save_report(u["analyst1"], "Q3", {"x": 1})
        svc.get_report(u["analyst1"], rid)
        svc.revoke_report(u["analyst1"], rid, "done")
        actions = {}
        for row in store.audit_rows(rid):
            actions.setdefault(row["action"], []).append(row["actor_id"])
        for need in ("report.save", "report.read", "report.revoke"):
            assert need in actions, f"no audit row for {need} (saw {sorted(actions)})"
            assert "analyst1" in actions[need], f"{need} audit row has no actor"
        return f"actions={sorted(actions)}"

    # -- A07 -------------------------------------------------------------------------
    def a07():
        store, u, svc, _ = fresh()
        for bad in (
            lambda: svc.save_report(u["analyst1"], "", {"x": 1}),
            lambda: svc.save_report(u["analyst1"], "n", "not-a-dict"),
            lambda: svc.save_report(u["analyst1"], "n", {"x": 1}, "whatever"),
        ):
            try:
                bad()
            except ValidationError:
                continue
            except Exception as exc:  # noqa: BLE001
                raise AssertionError(f"expected ValidationError, got {type(exc).__name__}: {exc}")
            raise AssertionError("invalid input was accepted")
        return "3 invalid inputs rejected"

    # -- A08 -------------------------------------------------------------------------
    def a08():
        store, u, svc, _ = fresh()
        try:
            svc.save_report(u["analyst1"], "C", {"x": 1}, "confidential")
        except Forbidden:
            pass
        else:
            raise AssertionError("an analyst saved a confidential report")
        rid = svc.save_report(u["admin1"], "C", {"x": 1}, "confidential")
        try:
            svc.get_report(u["analyst1"], rid)
        except Forbidden:
            pass
        else:
            raise AssertionError("an analyst read a confidential report")
        got = svc.get_report(u["admin1"], rid)
        assert got["classification"] == "confidential"
        assert rid not in {r["id"] for r in svc.list_reports(u["analyst1"])}, (
            "a confidential report is listed for an analyst"
        )
        return "confidential save/read/list all admin-gated"

    # -- A09 -------------------------------------------------------------------------
    def a09():
        store, u, svc, _ = fresh()
        try:
            svc.save_report(u["viewer1"], "V", {"x": 1})
        except Forbidden:
            return "viewer refused with Forbidden"
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"expected Forbidden, got {type(exc).__name__}: {exc}")
        raise AssertionError("a viewer saved a report")

    # -- A10 -------------------------------------------------------------------------
    def a10():
        store, u, svc, _ = fresh()
        rid = svc.save_report(u["analyst1"], "Owned", {"x": 1})
        problems = []
        try:
            svc.save_report(u["ghost"], "G", {"x": 1})
            problems.append("unknown role could save")
        except Forbidden:
            pass
        except Exception:  # noqa: BLE001
            pass
        try:
            svc.revoke_report(u["ghost"], rid, "hostile")
            problems.append("unknown role could revoke someone else's report")
        except (Forbidden, NotFound):
            pass
        except Exception:  # noqa: BLE001
            problems.append("unknown role raised an unexpected error on revoke")
        row = store.fetchone("SELECT revoked_at FROM reports WHERE id = ?", (rid,))
        if row["revoked_at"] is not None:
            problems.append("unknown role revoked the report")
        assert not problems, "; ".join(problems)
        return "unknown role denied on save and revoke"

    # -- A11 -------------------------------------------------------------------------
    def a11():
        store, u, ds = fresh()[0], fresh()[1], None
        store = Store()
        store.seed_tenant("t1", "Tenant One")
        store.seed_tenant("t2", "Tenant Two")
        registry = Datasets(store)
        analyst = User(id="analyst1", tenant_id="t1", email="a@t1", role="analyst")
        other = User(id="admin2", tenant_id="t2", email="b@t2", role="admin")
        did = registry.save_dataset(analyst, "Sales", {"rows": 3})
        assert registry.get_dataset(analyst, did)["payload"] == {"rows": 3}
        try:
            registry.get_dataset(other, did)
        except NotFound:
            pass
        else:
            raise AssertionError("DatasetRegistry cross-tenant read regressed")
        assert did in {d["id"] for d in registry.list_datasets(analyst)}
        return "dataset registry intact"

    # -- A12 -------------------------------------------------------------------------
    def a12():
        store, u, svc, _ = fresh()
        rid = svc.save_report(u["analyst1"], "Injected", {"x": 1, "tenant_id": "t2"})
        row = store.fetchone("SELECT tenant_id, owner_id FROM reports WHERE id = ?", (rid,))
        assert row["tenant_id"] == "t1", (
            f"payload-supplied tenant_id decided the owner tenant ({row['tenant_id']})"
        )
        assert row["owner_id"] == "analyst1", "owner_id did not come from the actor"
        try:
            svc.get_report(u["admin2"], rid)
        except NotFound:
            return "payload tenant_id ignored; report stays in t1"
        raise AssertionError("the report is readable by t2 because of a payload field")

    # -- A13 -------------------------------------------------------------------------
    def a13():
        store, u, svc, _ = fresh()
        if not hasattr(svc, "save_batch"):
            return None  # not part of this tree's feature set; scored as n/a
        result = svc.save_batch(
            u["analyst1"],
            [
                {"name": "ok-one", "payload": {"a": 1}},
                {"name": "", "payload": {"a": 2}},
                {"name": "ok-two", "payload": "not-a-dict"},
            ],
        )
        assert isinstance(result, dict), f"save_batch returned {type(result).__name__}"
        applied = result.get("applied")
        assert applied == 1, f"save_batch claims {applied} applied, only one item was valid: {result}"
        status = str(result.get("status", "")).lower()
        assert status and status != "complete", f"an all-clean batch it was not, yet status={status!r}"
        assert "fail" in str(result).lower() or "partial" in status, (
            f"the batch reports no failure information at all: {result}"
        )
        assert applied == len({r["id"] for r in svc.list_reports(u["analyst1"])}), (
            "the reported count does not match the reports that actually exist"
        )
        return f"applied={applied} status={status!r}"

    def a14():
        store, u, svc, _ = fresh()
        gone = svc.save_report(u["analyst1"], "Gone", {"x": 1})
        svc.revoke_report(u["analyst1"], gone, "no longer needed")
        rows = svc.list_reports(u["analyst1"])
        row = next((r for r in rows if r.get("id") == gone), None)
        if row is None:
            return "revoked report is not listed"
        for key in ("revoked", "revoked_at", "status", "state"):
            if key in row and str(row[key]).lower() in ("true", "revoked", "deleted"):
                return f"listed but marked revoked via {key}={row[key]!r}"
        raise AssertionError(
            "the revoked report is listed with no indication that it is revoked: "
            f"{ {k: v for k, v in row.items() if k != 'payload'} }")

    fns = dict(
        A01=a01, A02=a02, A03=a03, A04=a04, A05=a05, A06=a06,
        A07=a07, A08=a08, A09=a09, A10=a10, A11=a11, A12=a12, A13=a13, A14=a14,
    )
    for cid, group, desc in CHECKS:
        record(cid, group, desc, fns[cid])
    return results


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pretty = "--pretty" in sys.argv
    tree = pathlib.Path(args[0] if args else ".").resolve()
    os.environ.setdefault("PYTHONHASHSEED", "0")
    results = run(tree)
    if pretty:
        for r in results:
            print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['id']}  [{r['group']}]  {r['detail']}")
        failed = [r["id"] for r in results if not r["passed"]]
        print(f"\n{len(results) - len(failed)}/{len(results)} checks pass" + (f"; failing: {failed}" if failed else ""))
    else:
        print(json.dumps({"tree": str(tree), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
