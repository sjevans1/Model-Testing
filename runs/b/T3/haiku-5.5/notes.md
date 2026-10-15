# Saved Reports: design notes and verification

## What changed

- src/reportcore/service.py: SavedReportsService implemented (save_report, get_report,
  list_reports, revoke_report). Public signatures unchanged. DatasetRegistry untouched.
  Added helpers _validate_report_id and _validate_reason, and imported ReportCoreError.
- tests/test_saved_reports.py: new, 28 tests.
- tests/test_smoke.py: not edited.
- No new dependencies, stdlib only.

## Design decisions

Save
- Validation runs first (name, payload, classification), then role gates:
  analyst or higher to save, admin for confidential. Mirrors DatasetRegistry.
- tenant_id and owner_id are taken from the actor. The payload is never read for
  tenant, owner or classification. A test confirms a payload containing
  tenant_id/owner_id/classification does not change the stored row.
- The snapshot is stored as canonical JSON (sort_keys, compact separators) with a
  sha256 of that exact string, in report_snapshots next to the reports row. Report
  and snapshot are inserted in one transaction, with the audit row (report.save).

Get
- Lookup is scoped by id AND tenant_id in SQL. A foreign tenant, an unknown id and a
  revoked report all raise NotFound with the same message, so existence is not leaked.
  A test checks the foreign-tenant error text equals the missing-id error text.
- Confidential reports raise Forbidden for non-admins (same as datasets).
- The snapshot hash is recomputed on read; a mismatch raises ReportCoreError. This is
  a tamper check, not something the brief asked for, and it is covered by a test.
- Successful reads write a report.read audit row. Failed reads write none.

List
- Tenant-scoped, excludes revoked reports, hides confidential reports from
  non-admins, sorted by name. Writes a report.list audit row.

Revoke
- Analyst or higher, and the actor must be the owner or an admin (otherwise Forbidden).
  Foreign tenant or unknown id gives NotFound. A second revoke gives Conflict.
- Only the reports row changes (revoked_at, revoked_by, revoke_reason). The test
  compares the report_snapshots row before and after and expects it identical.
- reason is a string of at most 500 characters, default "".
- Audit row report.revoke carries the reason in detail.

Known limits / judgement calls
- A same-tenant analyst revoking a confidential report they own gets Forbidden, since
  they cannot read it. Analysts cannot create confidential reports, so this only
  arises if ownership is changed directly in the DB. This is covered by a test.
- Get and list do not check for revocation status separately from the tenant query.
  Revoked get returns NotFound, not a distinct status, to keep the disclosure rule.
- The audit table stores the content hash as the detail on report.save. The payload
  itself is not written to audit.

## How to reproduce

From the repository root:

    sh run_checks.sh

Expected: "Ran 30 tests ... OK" (2 from test_smoke, 28 from test_saved_reports).

Single module:

    PYTHONPATH=src python3 -m unittest tests.test_saved_reports -v

## Verification record

- First full run of run_checks.sh after the implementation: passed, 30/30. No
  correction cycles were needed.
- Before editing, run_checks.sh passed on the untouched tree (2 tests), and fixture
  hashes matched .bench-fixture-baseline.json.
- An LSP reported an undefined name, ReportCoreError, after the first edit. The import
  was added and the run was clean. The LSP also shows an unresolved "reportcore"
  import in the test file. This is an editor-path issue only; unittest passes because
  the tests insert src/ on sys.path, the same as test_smoke.py.
