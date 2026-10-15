# Findings — SavedReportsService authorization review

## D1 — Report and snapshot reads were not tenant-scoped

- Defect: `get_report` selected a report by ID and fetched its snapshot without checking the authenticated actor's tenant.
- Impact: a user who obtained a foreign report ID could read its metadata and complete snapshot payload; the response disclosed a cross-tenant object.
- Evidence: the shipped `get_report` queried `reports WHERE id = ?` and proceeded directly to `report_snapshots`. `test_foreign_get_and_revoke_are_indistinguishable_from_missing` now verifies a foreign read raises the same `NotFound("no such object")` as a missing ID, and that no foreign read audit is written.
- Fix: gate recognized viewer roles, call `require_tenant` before fetching the snapshot, and use the existing `may_read_classification` primitive before returning content.
- Test: `tests/test_saved_reports_authz.py::TestSavedReportsAuthorization.test_foreign_get_and_revoke_are_indistinguishable_from_missing`.

## D2 — Report listing exposed other tenants' reports

- Defect: `list_reports` queried all reports without a tenant predicate.
- Impact: names, classifications, owner IDs, and report IDs from unrelated tenants were disclosed.
- Evidence: the shipped query ended in `ORDER BY name` with no `WHERE tenant_id`; the new listing test creates reports in two tenants and asserts only the caller tenant's report is returned.
- Fix: scope the query to `actor.tenant_id`; apply the classification visibility primitive to each returned row.
- Test: `tests/test_saved_reports_authz.py::TestSavedReportsAuthorization.test_list_is_tenant_scoped_and_reports_actual_revocation`.

## D3 — Revocation was not tenant-scoped

- Defect: `revoke_report` looked up and updated by report ID alone.
- Impact: a caller from another tenant could revoke a report, while the distinction between missing and foreign objects was observable.
- Evidence: the shipped update used only `WHERE id = ?`; the new test checks that foreign revocation raises the same `NotFound("no such object")` as a missing report and leaves the report unchanged.
- Fix: enforce `require_tenant` before authorization and constrain the update by both report ID and actor tenant.
- Test: `tests/test_saved_reports_authz.py::TestSavedReportsAuthorization.test_foreign_get_and_revoke_are_indistinguishable_from_missing`.

## D4 — Any same-tenant member could revoke another owner's report

- Defect: revocation had no owner/admin authorization check.
- Impact: a tenant member could revoke reports they did not own, disrupting other users' saved work.
- Evidence: the shipped `revoke_report` updated the row after existence lookup without checking `owner_id` or role. The new test verifies a same-tenant peer is denied, the owner can revoke, and a tenant admin can revoke.
- Fix: after tenant validation, permit only the report owner or an actor whose role is exactly the tenant `admin` role.
- Test: `tests/test_saved_reports_authz.py::TestSavedReportsAuthorization.test_only_owner_or_tenant_admin_can_revoke`.

## D5 — Caller payload could choose a report's tenant

- Defect: `save_report` used `payload["tenant_id"]` when present instead of the authenticated actor's tenant. The stored owner was already actor-derived.
- Impact: a caller could assign a report to another tenant, breaking isolation and creating inconsistent ownership/audit scope.
- Evidence: the shipped implementation set `tenant_id = str(payload.get("tenant_id") or actor.tenant_id)`. The new test supplies spoofed tenant and owner values and asserts the report attributes remain `t1` and `u1` from the actor.
- Fix: derive both report tenant and owner exclusively from `actor`; caller payload fields remain snapshot data and do not set authorization attributes.
- Test: `tests/test_saved_reports_authz.py::TestSavedReportsAuthorization.test_save_uses_authenticated_tenant_and_owner`.

## D6 — Confidential report visibility was not enforced

- Defect: `get_report` did not check classification; listing also exposed confidential report entries to non-admins.
- Impact: tenant members without admin privilege could read confidential snapshots and discover classified report metadata.
- Evidence: the shipped `get_report` returned the snapshot without consulting classification, and `list_reports` included every row. The new test verifies non-admin read denial and list omission, admin read success, and audit recording.
- Fix: require confidential-read permission through `may_read_classification`; require admin to create confidential reports and validate classification values.
- Test: `tests/test_saved_reports_authz.py::TestSavedReportsAuthorization.test_confidential_reports_are_admin_only_and_reads_are_audited`.

## D7 — Role authorization failed open and report operations lacked consistent role gates

- Defect: `require_role` accepted unknown roles because it checked the minimum only for roles present in `ROLE_LEVEL`. Saved-report entry points also lacked consistent role checks.
- Impact: empty or unrecognized roles could pass a role check; callers could reach report reads, listings, revocation, and batch operations without a recognized role.
- Evidence: the shipped primitive contained `if actor.role in ROLE_LEVEL and ...`; report save/list/revoke did not consistently call it. New tests exercise empty and unrecognized roles at every saved-report entry point, and verify viewers cannot save.
- Fix: make `require_role` deny every unrecognized role; gate reads/list/revocation at viewer, saves/batches at analyst, and confidential creation at admin. `may_read_classification` now also denies unknown roles and unknown classifications.
- Test: `tests/test_saved_reports_authz.py::TestSavedReportsAuthorization.test_unknown_role_is_denied_at_every_service_entry_point`.

## D8 — Batch results claimed failed items were saved

- Defect: `save_batch` swallowed all exceptions, returned `applied=len(items)`, and always reported `status="complete"`.
- Impact: callers received false success counts and could not distinguish complete, partial, or failed batches from actual writes.
- Evidence: the shipped implementation used a broad exception handler and reported the request size as applied. The new mixed-validity batch test verifies one successful ID, two failures, an applied count of one, and partial status.
- Fix: validate the batch and item shapes, count only successful saves, report a failed count, and distinguish complete/partial/failed outcomes while allowing unexpected non-domain failures to propagate.
- Test: `tests/test_saved_reports_authz.py::TestSavedReportsAuthorization.test_batch_reports_successes_and_failures_truthfully`.

## Audit verification

No separate audit defect was found: successful report saves and revocations already append audit rows, and reads/listings already record audit rows. The new tests verify mutation audit entries, successful ordinary and confidential reads, listing, and the absence of a foreign-read audit.
