# SavedReportsService acceptance test plan

Run the unchanged smoke test and these acceptance tests with:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

The acceptance tests are in `tests/test_saved_reports.py`; they use only `unittest`,
`sqlite3` through the shipped `Store`, and the Python standard library. Each test creates
isolated state. The concurrency test creates a temporary SQLite database and gives every
worker its own connection.

## Test claims and falsification

- `test_analyst_save_round_trip_and_canonical_snapshot`: an authorized analyst can save a
  report and a same-tenant viewer can retrieve the correct owner, tenant, trimmed name,
  content and canonical JSON/hash. It compares both the API result and persisted snapshot,
  so a response-only success or malformed serialization fails.
- `test_invalid_name_payload_and_classification_are_rejected_without_writes`: blank names,
  non-object payloads, and unsupported classifications raise `ValidationError` and do not
  create a report. The database count makes a validation error raised after a write fail.
- `test_unknown_roles_fail_closed_in_role_gate`: an unrecognized role is denied by the
  shared role gate rather than receiving access because it is absent from the known-role
  map. This directly exercises the fail-closed rule.
- `test_viewer_and_unknown_role_cannot_create_reports`: viewer and unknown roles are denied
  report creation with `Forbidden`; a database count detects fail-open creation.
- `test_confidential_report_is_admin_only_for_get_and_list`: tenant admins may retrieve
  confidential content; analysts/viewers may not. The list comparison checks that
  confidential records are excluded for non-admins while an internal report remains
  visible, and that admins see both.
- `test_payload_tenant_id_cannot_move_report_or_grant_foreign_access`: a caller-controlled
  `payload.tenant_id` cannot change the stored tenant; the foreign tenant receives
  `NotFound` and does not see the report in its list.
- `test_foreign_list_and_reads_are_tenant_scoped`: a report from another tenant is absent
  from the caller's list and reads as `NotFound`; a genuinely missing id has the same
  exception class, avoiding an existence oracle.
- `test_revoke_requires_admin_and_foreign_revoke_is_indistinguishable_from_missing`:
  viewer/analyst revocations are denied, cross-tenant revoke is `NotFound`, and failed
  attempts leave revocation state untouched. An admin revoke records the timestamp,
  actor and reason.
- `test_current_role_is_enforced_after_demotion_and_promotion`: the same principal's
  lower current role loses confidential read and revoke access; promotion to admin grants
  confidential read and revoke. This would catch authorization based on stale role state.
- `test_revocation_preserves_snapshot_bytes_and_hash`: payload JSON and hash in storage are
  byte-for-byte unchanged by revoke; an authorized post-revoke read reports the same
  content/hash and the revoked flag.
- `test_revoked_reports_are_not_presented_as_saved_in_list`: a revoked report is not
  returned as an active saved report; an active sibling remains listed.
- `test_duplicate_batch_submissions_are_each_counted_and_persisted`: two identical
  submissions create two separately persisted reports under the current create-per-item
  API. The test checks status/count, distinct IDs and exact correspondence with storage,
  detecting duplicate loss or inflated success counts.
- `test_batch_count_and_status_match_a_mixed_success_failure_batch`: for two valid items
  and one invalid item, `applied` and `saved` reflect the two actual writes and the status
  is `partial`, not `complete`. It then reads each returned id and checks the database
  count, catching fabricated IDs and swallowed failures reported as success.
- `test_batch_with_no_successes_reports_failure_and_zero_applied`: an all-invalid batch
  returns no ids, reports zero applied and has `failed` status; the database count checks
  that no failed item was persisted.
- `test_concurrent_duplicate_saves_are_not_lost_or_corrupted`: six simultaneous identical-
  name submissions, each over its own SQLite connection, all produce distinct persisted
  reports and snapshots with matching hashes. A lost write or snapshot mismatch fails.

## Seeded-defect sensitivity evidence

The shipped implementation itself contains seeded defects (explicitly marked D1-D3, D5-D6
and D8 in `src/reportcore/service.py`, and D4 in `src/reportcore/authz.py`). Running the command
above against that unchanged implementation produced `Ran 16 tests` and `FAILED (failures=25)`
(including subtest failures).
The observed assertion failures include the following direct detections:

- tenant spoofing (`test_payload_tenant_id_cannot_move_report_or_grant_foreign_access`),
  foreign list/read exposure (`test_foreign_list_and_reads_are_tenant_scoped`), and
  cross-tenant reporting/list exposure detect D5/D1/D6;
- confidential reads and role-gated revoke failures in
  `test_confidential_report_is_admin_only_for_get_and_list`,
  `test_current_role_is_enforced_after_demotion_and_promotion`, and
  `test_revoke_requires_admin_and_foreign_revoke_is_indistinguishable_from_missing`
  detect missing authorization (D2/D3); report-creation failures detect the missing save
  gate, while `test_unknown_roles_fail_closed_in_role_gate` directly detects D4;
- unsupported classification acceptance in
  `test_invalid_name_payload_and_classification_are_rejected_without_writes` detects the
  missing classification validation;
- mixed-batch over-reporting in
  `test_batch_count_and_status_match_a_mixed_success_failure_batch` detects D8;
- revoked-list leakage in `test_revoked_reports_are_not_presented_as_saved_in_list`
  detects D6.

This run is expected to be red on the shipped defective implementation: these tests are
acceptance assertions, not tests weakened to make the existing code green. The normal
round-trip, stored snapshot immutability, duplicate persistence and concurrent write cases
also exercise positive paths. The captured run demonstrated the seeded defects fail the
corresponding assertions rather than passing regardless of behavior.

## Known gaps and contract boundaries

- `SavedReportsService` exposes no report update API or optimistic concurrency token, so
  there is no meaningful concurrent-update/version-conflict contract to assert. The
  concurrency test covers concurrent creates; it does not invent update semantics.
- Duplicate behavior has no idempotency-key or uniqueness contract. This suite checks the
  implementation's create-per-item behavior and requires returned counts/IDs to match
  actual persisted records; it does not claim repeated requests are idempotent.
- The batch response schema does not define per-item error details. Tests require accurate
  saved IDs/count and a non-complete partial status, but cannot check a failure reason
  without making up an undocumented field.
- The batch contract does not define transaction atomicity or behavior after storage-level
  failures. The mixed validation failure covers partial success; disk-full, process crash,
  and transaction rollback behavior remain untested.
- Audit-row contents/counts and payloads containing values unsupported by JSON are outside
  the three stated claims and are not exhaustively tested here.
