# T8 test plan: SavedReportsService acceptance tests

## How to run

    PYTHONPATH=src python3 -m unittest discover -s tests

Against the shipped `src/`: 52 tests run, 22 fail, 30 pass (includes the untouched smoke test).
Against a corrected reference copy (`mutation/ref`, which is `src/` with `SavedReportsService`
rewritten and the D4 fail-open fixed in `authz.py`): 52 run, 52 pass.
The mutation harness (`mutation/run_mutants.py`, output in `mutation/run_output.txt`) applies
20 seeded defects to the reference, one at a time: 20 of 20 are detected.

The shipped failures are expected. They are the claims being false, not test bugs.
All tests use only the stdlib. Tests are in-memory sqlite (`Store()`), so they run without a DB server.

## Files

- `tests/_support.py`: shared fixtures (two tenants, viewer/analyst/admin per tenant, helpers).
  The underscore prefix keeps it out of discovery.
- `tests/test_saved_reports_access.py`: claim 1 (permissions and tenant isolation), plus audit.
- `tests/test_saved_reports_snapshots.py`: claim 2 (revocation keeps snapshot and hash), snapshot
  integrity, and duplicate submissions.
- `tests/test_saved_reports_batch.py`: claim 3 (batch reporting truth), plus partial failures.
- `tests/test_dataset_regression.py`: regression guard for DatasetRegistry, which CLAIMS.md says is
  believed correct.
- `tests/test_smoke.py`: untouched.

## Claim 1: "Saved reports are permission safe"

Claim: a report and its snapshot are readable only by members of the owning tenant; confidential
reports only by tenant admins; a caller cannot move a report into another tenant with a tenant id.

| Test | What it claims | How it would detect the claim being false | Shipped result |
|---|---|---|---|
| test_save_then_get_returns_payload_and_owning_tenant | normal round trip keeps payload and tenant | a corrupted payload or wrong tenant_id is an assertion mismatch | pass |
| test_same_tenant_viewer_can_read_internal_report | viewers read internal reports in their tenant | a read gate that's too strict fails the assertion | pass |
| test_list_contains_own_tenant_reports_only | list shows only own tenant | a list leaking other tenants' names fails | FAIL (D6) |
| test_empty_name_is_rejected_and_nothing_is_stored | invalid name rejected, no row written | a row written despite the error fails the count check | pass |
| test_non_object_payload_is_rejected | payload must be an object | an accepted list payload fails assertRaises | pass |
| test_unknown_classification_is_rejected | unknown label rejected before the write | a stored `"Confidential "` row fails the count | FAIL |
| test_missing_report_id_is_not_found | unknown id is NotFound | a different exception or a success fails | pass |
| test_confidential_report_hidden_from_analyst_and_viewer | confidential needs admin on read | a read with no classification check returns the payload and fails | FAIL (D3) |
| test_confidential_report_readable_by_tenant_admin | admins can read confidential | an over-strict gate fails | pass |
| test_confidential_report_not_listed_for_analyst | confidential not listed for non-admins | list shows the name to an analyst and fails | FAIL |
| test_revoked_report_is_not_listed_as_an_active_saved_report | revoked report not shown as active | listed with revoked=False fails. Hidden or listed-as-revoked both pass | FAIL (D6) |
| test_viewer_cannot_save_a_report | write needs analyst | a row written by a viewer fails the count | FAIL |
| test_viewer_cannot_revoke | revoke needs admin | a changed revoked flag fails | FAIL (D2) |
| test_unknown_role_cannot_revoke | unknown role is denied (fail-closed) | the revoke succeeds and the flag changes, which fails | FAIL (D4) |
| test_foreign_admin_cannot_read_report | foreign tenant admin gets no read | a returned payload raises the failure | FAIL (D1) |
| test_foreign_read_error_is_identical_to_missing_id | foreign id errors the same as a missing id (no existence oracle) | a Forbidden or different message fails equality | FAIL |
| test_foreign_admin_cannot_read_confidential_report | foreign admin can't read confidential | a returned payload fails assertRaises | FAIL |
| test_foreign_user_cannot_see_report_in_list | foreign list excludes the name | a name in the foreign list fails | FAIL (D6) |
| test_foreign_user_cannot_revoke_report | foreign revoke denied, flag unchanged | a changed flag fails | FAIL (D2) |
| test_tenant_id_in_payload_cannot_move_report_into_another_tenant | payload tenant_id is ignored | a row with tenant_id t2 fails the t1 check | FAIL (D5) |
| test_demoted_admin_loses_confidential_access | a demoted user loses access immediately | a demoted user still reading a confidential report fails | FAIL (D3) |
| test_promoted_analyst_gains_confidential_access | promotion grants access | an over-strict gate fails | pass |
| test_demoted_admin_cannot_revoke | a demoted user can't revoke | the flag change fails | FAIL (D2) |
| test_save_get_list_revoke_each_write_an_audit_row | audit row per mutation and privileged read | a missing or reordered audit action fails the list equality | pass |
| test_audit_row_records_the_acting_user | audit records actor and tenant | a wrong actor_id fails | pass |

Role changes are modelled as a new `User` object with the new role. That matches the README
convention that `User` is trusted input. The service has no session or role store to
revoke, so a true mid-session revocation can't be tested. See gaps.

## Claim 2: "Revocation never changes the stored snapshot; the content hash is stable"

| Test | What it claims | How it would detect the claim being false | Shipped result |
|---|---|---|---|
| test_revoke_leaves_snapshot_row_byte_identical | snapshot row unchanged by revoke | any column change, or a deleted row, fails the tuple comparison | pass (mutants M13–M15 are caught) |
| test_content_hash_and_payload_are_stable_across_revocation | hash and payload identical before and after | a changed hash or payload fails | pass |
| test_stored_hash_matches_canonical_payload_before_and_after_revoke | stored hash equals sha256 of canonical JSON | a stale or rewritten hash fails | pass |
| test_revoke_only_changes_report_status_columns | revoke touches only status columns | a changed name, classification or tenant fails (M16) | pass |
| test_revoking_twice_keeps_snapshot_and_revoked_state | repeat revoke is harmless | a changed snapshot fails | pass |
| test_revoked_report_content_still_readable_by_owner_tenant | revoked content still readable by the owner | a missing payload or a raised error fails | pass |
| test_hash_is_canonical_so_key_order_does_not_change_it | key order does not change the hash | a non-canonical hash fails | pass |
| test_different_payloads_produce_different_hashes | distinct payloads hash differently | a constant hash fails | pass |
| test_returned_hash_matches_recomputed_hash_of_returned_payload | returned hash matches returned payload | a mismatched hash fails | pass |
| test_identical_resubmission_leaves_first_snapshot_intact | second identical save doesn't alter the first | a changed first snapshot fails | pass |
| test_resubmission_with_different_payload_does_not_rewrite_first_snapshot | second save with different payload doesn't rewrite the first | a rewritten first payload or hash fails | pass |

Claim 2 is mostly kept by the shipped code. The shipped code has no defect that breaks it, so
these tests pass on the shipped tree. Their value is the mutation evidence below.
The duplicate-submission tests check only that the first snapshot stays intact. They don't assert
whether a duplicate is accepted or rejected, because the claims don't say.

## Claim 3: "`save_batch()` reports the truth about a batch"

Claim: `applied` is the count actually saved, and `status` is `complete` only when every item was saved.

| Test | What it claims | How it would detect the claim being false | Shipped result |
|---|---|---|---|
| test_all_valid_items_saved_and_reported_complete | a clean batch saves all items, reports complete | a wrong count or status fails | pass |
| test_returned_ids_are_real_reports_owned_by_the_actor_tenant | every returned id is a real own-tenant row | a phantom id fails the row lookup | pass |
| test_empty_batch_saves_nothing | empty batch reports 0 | a non-zero count fails | pass |
| test_invalid_item_is_not_counted_and_status_is_not_complete | an invalid item is not counted and status is not complete | `applied` 3 or status complete fails (D8) | FAIL |
| test_unauthorised_item_is_not_counted_as_saved | a viewer batch reports 0 saved and not complete | `applied` > 0 or status complete fails (D8) | FAIL |
| test_confidential_item_rejected_for_analyst_is_not_counted | a rejected confidential item is not counted | `applied` 2 fails (D8) | FAIL |
| test_all_items_failing_reports_zero_and_not_complete | all-failing batch reports 0 and not complete | `applied` = requested count fails (D8) | FAIL |
| test_failed_items_leave_no_partial_rows_behind | stored rows equal the reported ids | a stored row not in `saved`, or a reported id not stored, fails | pass |
| test_tenant_id_in_batch_payload_is_ignored | batch payload tenant_id ignored | a row with tenant t2 fails | FAIL (D5) |
| test_non_dict_items_are_not_reported_as_saved | non-dict items not counted | `applied` ≠ rows stored fails | FAIL (D8) |

The clean-batch test passes on the shipped tree. On a clean batch, `applied` equals the saved
count, so that is the one batch case where the shipped count is correct. The defect only shows
when items fail.

## Duplicate submissions and conflicting updates

Duplicates are covered by the snapshot tests (identical and different-payload resubmission). There is
no concurrency test. See gaps.

## Mutation evidence

The reference copy passes. Each mutant reintroduces one defect into the reference and must make
at least one test fail. Results from `mutation/run_output.txt`:

- M1 get_report no tenant scope (D1): detected (4 failures)
- M2 get_report ignores classification (D3): detected (2)
- M3 get_report returns Forbidden for foreign tenant, not NotFound: detected (1 failure, 3 errors)
- M4 revoke no tenant check (D2): detected (1)
- M5 revoke no role check (D2): detected (3)
- M6 authz fails open for unknown roles (D4): detected (1)
- M7 save trusts payload tenant_id (D5): detected (2)
- M8 list not tenant-scoped (D6): detected (2)
- M9 list shows revoked reports as active, revoked hard-coded False (D6): detected (1)
- M10 list ignores classification: detected (2)
- M11 viewer can save (write gate removed): detected (2)
- M12 unknown classification accepted: detected (1)
- M13 revoke rewrites snapshot payload: detected (4)
- M14 revoke changes snapshot hash: detected (4)
- M15 revoke deletes snapshot row: detected (6 errors)
- M16 revoke edits name: detected (1)
- M17 batch always complete (D8): detected (5)
- M18 batch counts requested items (D8): detected (5)
- M19 batch complete if any item saved: detected (3)
- M20 batch hides failures: detected (5)

Mutation design notes:
- The mutants are my own, built from the shipped defect comments and from the claims. They are not
  the authors' defect list, and the D-numbers are only labels from `src/` comments.
- M9 was first written as a filter-only change. The reference already hides revoked rows, so
  that mutant was equivalent to the reference and no test could catch it. The test was therefore
  relaxed to accept hiding or listing as revoked, and M9 was rewritten to hard-code
  `revoked: False` and drop the filter, which reproduces the shipped behaviour.
- The reference itself is my correction. It is not the authors' fix, so "the claims pass on a correct
  implementation" is shown only for my reading of "correct".

## Remaining coverage gaps

1. Concurrency and conflicting updates: no test. The brief lists them, but the service has no
   update-with-version API, so there's no conflict path to test. Concurrent writes to sqlite
   from two threads would test the store, not the claims.
2. Mid-session revocation: role changes are tested as a new `User` object. The service has no
   session or permission store, so a "revoked while holding a session" case can't be tested.
3. Duplicate submissions: tests check only that the first snapshot is not altered. They don't assert
   whether a duplicate should be rejected, because the claims are silent on it.
4. Batch items with an unknown extra field, a non-string `name`, and a non-string `classification`
   (e.g. a list) are not tested. A non-hashable classification could raise a TypeError that
   `save_batch` doesn't catch.
5. `DatasetRegistry` regression covers the basics only. It has no snapshot-revocation, batch, or
   concurrency coverage, because the registry has no such features.
6. Audit completeness for the failed-path rows (e.g. a denied read) is not asserted. The conventions
   say denied actions are not audited, so the suite doesn't pin that either way.
7. `list_reports` audit rows are checked only for existence, not content.
8. Only in-memory sqlite. File-backed and multi-connection behaviour is untested.
