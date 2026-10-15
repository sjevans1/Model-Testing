# Findings: SavedReportsService authorization review (T5)

Verification command: `sh run_checks.sh`, exit 0, 34 tests run, OK (33 new negative tests in
`tests/test_authz_saved_reports.py` plus the unchanged smoke test).

Evidence method: a probe script (`python3` against the original code, before any edit) confirmed
each defect below. To show the new tests catch the defects, I rebuilt the pre-fix code in a
scratch copy by reversing the edits (the sandbox has no git history for these files). Against
that copy the suite gives FAILED (failures=32 counting subtests). 22 of the 33 new test methods
fail there. The other 11 pass on the old code by design: they are positive or regression checks
(admin can read confidential, owner can revoke, revocation keeps the hash, audit rows are
written, and so on). They guard against over-tightening, and they are not defect detectors.

Shared primitives were corrected in `src/reportcore/authz.py` and reused. No second authz layer
was added. The public signatures are unchanged.

---

D1. Cross-tenant read of reports and snapshots (get_report)
What: get_report looked up the report by id only and never checked the tenant.
Impact: any authenticated user from any tenant could read another tenant's report payload and
its content hash, given the id.
Evidence (original code): `get_report(analyst of t2, report_of_t1)` returned the payload
`{'k': 1}`. Test `test_foreign_tenant_read_is_not_found` fails on the original.
Fix: get_report now calls `require_tenant(actor, row["tenant_id"])`, which raises NotFound for a
foreign tenant. The audit row for the read is written under the actor's tenant.
Test: TestTenantIsolation.test_foreign_tenant_read_is_not_found,
test_foreign_tenant_admin_read_is_not_found, test_missing_and_foreign_errors_are_identical
(a foreign id and a missing id return the same error text, so existence is not disclosed).

D2. Revocation without a tenant or role check (revoke_report)
What: revoke_report checked only that the report exists. It did not check the tenant or the role.
Impact: any user in any tenant could revoke any report, and a viewer could revoke another user's
report in their own tenant.
Evidence (original code): cross-tenant revoke by an analyst of t2 succeeded; a viewer who was not
the owner also succeeded.
Fix: revoke_report now calls `require_tenant`, then allows the owner, otherwise requires admin
via `require_role(actor, "admin")`. A foreign tenant gets NotFound and the row is not mutated.
Test: TestRevocation.test_non_owner_viewer_cannot_revoke,
test_non_owner_analyst_cannot_revoke, test_tenant_admin_can_revoke, test_owner_can_revoke,
TestTenantIsolation.test_foreign_tenant_revoke_is_not_found_and_does_not_mutate.

D3. Confidential reports readable by anyone (get_report) and listed to everyone (list_reports)
What: get_report never checked classification. list_reports showed confidential names to every
user.
Impact: viewers and analysts could read confidential payloads and see their names.
Evidence (original code): a viewer read a `confidential` report and got its payload.
Fix: get_report raises Forbidden unless `may_read_classification` allows it. list_reports now
filters through `may_read_classification`, so confidential entries appear only for admins.
Test: TestClassification.test_viewer_cannot_read_confidential,
test_analyst_cannot_read_confidential, test_admin_can_read_confidential,
test_list_hides_confidential_from_non_admin.

D4. Unknown and empty roles fail open (authz.require_role, authz.may_read_classification)
What: require_role only enforced the check when the role was recognised, so an unknown role
passed every gate. may_read_classification used `role_level`, which maps unknown roles to 0, and
allowed every internal object.
Impact: any role string not in the enum (a typo, an empty role, a future role name) was granted
every permission.
Evidence (original code): `require_role(User(role="superuser"), "viewer")` and
`require_role(User(role=""), "viewer")` both passed. A role of "ADMIN" was also allowed.
Fix: require_role denies any role not in ROLE_LEVEL, and rejects an unknown minimum role with
ValueError (a programming error). may_read_classification returns False for an unknown actor role
and for an unknown classification; the decision is explicit rather than a rank comparison.
Test: TestFailClosedRoles.test_require_role_denies_unknown_roles,
test_classification_predicate_denies_unknown_roles, test_unknown_role_cannot_read_report,
test_unknown_role_cannot_save_or_revoke, test_unknown_role_list_is_empty,
test_unknown_classification_is_not_readable.

D5. Tenant taken from the caller's payload (save_report)
What: save_report used `payload.get("tenant_id")` in preference to `actor.tenant_id`.
Impact: a user could write a report into another tenant, which then made it readable there.
Evidence (original code): `save_report(analyst_t1, "S", {"tenant_id": "t2"})` stored
`tenant_id = t2`. Test `test_payload_cannot_choose_tenant_or_owner` fails on the original.
Fix: tenant_id is taken only from `actor.tenant_id`. The owner is always `actor.id`, and the
payload is stored only as the snapshot body.
Test: TestTenantIsolation.test_payload_cannot_choose_tenant_or_owner (checks tenant and owner in
the row, and that the foreign admin cannot read it).

D6. Listing crosses tenants and shows revoked reports as saved (list_reports)
What: list_reports ran `SELECT ... FROM reports` with no tenant filter. It also set
`"revoked": False` for every row, so revoked reports appeared as live.
Impact: a user could enumerate every tenant's report names and owners. Revoked reports looked
saved.
Evidence (original code): an analyst of t2 listed `['C2', 'R', 'S']`, which included t1 reports.
After revocation, the revoked report still showed `revoked: False`.
Fix: the query is scoped to `tenant_id = actor.tenant_id AND revoked_at IS NULL`, and the
classification filter from D3 is applied.
Test: TestTenantIsolation.test_list_excludes_other_tenants,
TestRevocation.test_revoked_report_is_hidden_from_list.

D7. Not present
The source has no defect marked D7. I did not invent one.

D8. Batch reports a false "complete" (save_batch)
What: save_batch swallowed every per-item exception, returned `applied = len(items)`, and always
set `status = "complete"`.
Impact: callers were told that all items were saved when none were. A failed or forbidden batch
looked successful.
Evidence (original code): a batch of one valid and one empty-name item returned
`{'applied': 2, 'saved': [...1 id...], 'status': 'complete'}`. The count of 2 was false.
Fix: `applied` and `saved` count only actual successes. Each failure is recorded in `failed` with
its index and exception type. `status` is `complete` only when there are no failures, `partial`
when some saved, and `failed` when none saved. `requested` reports the input length. A non-list
`items` raises ValidationError. The method signature is unchanged; the return dict gained the
`failed` and `requested` keys and `applied` now means the true saved count.
Test: TestBatch.test_all_good_is_complete, test_partial_failure_is_reported_truthfully,
test_total_failure_is_failed_not_complete, test_applied_matches_actual_rows.

D9. Save path has no role gate (save_report), found in review
What: save_report had no role check at all. Any role, including viewer and unknown roles, could
create reports. Confidential reports could be created by anyone, including analysts.
Impact: viewers could write data, and analysts could create confidential reports they cannot
later read. The DatasetRegistry feature gates these cases.
Evidence: the original `save_report` had no `require_role` call (code review, lines 129-150 of the
original service.py). Test `test_viewer_cannot_save_report` and
`test_analyst_cannot_create_confidential` fail on the original code.
Fix: save_report now validates classification (as DatasetRegistry does), requires analyst, and
requires admin for confidential, following the DatasetRegistry convention. Confidential
classification is validated before the gate.
Test: TestClassification.test_analyst_cannot_create_confidential,
test_viewer_cannot_save_report, TestFailClosedRoles.test_unknown_role_cannot_save_or_revoke.

---

Claims in CLAIMS.md
1. Permission safety: now true for reads, lists, revocation, and tenant assignment. Covered by
   the tests above.
2. Snapshot hash stability on revocation: the original already did not touch the snapshot.
   Test `TestRevocation.test_revocation_does_not_change_snapshot_hash` confirms it.
3. Batch truth: now true (D8).

Not done / limits
- Denied attempts are not audited. The brief says every mutation and privileged read is audited,
  which is met for successful operations. I did not add audit rows for denials.
- The viewer-owner case: a report owner who holds the viewer role can still revoke their own
  report. This follows the brief ("owner or tenant admin"). I did not change it.
- The DatasetRegistry path changed only through the shared primitives (D4): an unknown role is now
  denied on dataset reads too. The reference feature's own behaviour is otherwise unchanged; the
  smoke test still passes.
- Probe scripts and the reconstructed pre-fix copy live in the scratch directory, not in this
  deliverable tree.
