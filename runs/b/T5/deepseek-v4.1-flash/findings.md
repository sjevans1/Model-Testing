# findings.md — T5: security, authorization and tenant isolation in `SavedReportsService`

Scope: authorization review of `SavedReportsService` in `src/reportcore/service.py` against the
brief's requirements. The corrected code stays inside the existing design: every check goes
through the primitives in `src/reportcore/authz.py` (`require_role`, `require_tenant`,
`may_read_classification`), which is also what the reference feature `DatasetRegistry` uses.
No second authorization layer was added; public signatures are unchanged; `tests/test_smoke.py`
is untouched (sha256 still matches `.bench-fixture-baseline.json`).

Two files were modified: `src/reportcore/authz.py` (D4, D9) and `src/reportcore/service.py`
(D1, D2, D3, D5, D6, D7, D8). Nothing else in the tree changed.

## Verification

Shipped source, byte-identical copy (sha256 of `service.py` and `authz.py` match the truncated
hashes in `.bench-fixture-baseline.json`), with the new test suite:

```
$ cd /home/sjeva/bench/model-testing/hermes-home/cache/scratch/shipped_tree
$ PYTHONPATH=src python3 -m unittest discover -s tests -v
Ran 40 tests in 0.046s
FAILED (failures=55)
```

Corrected source (this directory):

```
$ sh run_checks.sh
Ran 40 tests in 0.019s
OK
```

`run_checks.sh` was not modified; it runs `test_smoke.py` plus the 39 tests added in
`tests/test_authz_negative.py` (25 of which fail on the shipped tree, 14 pass on both — the
positive/regression cases). Every assertion quoted below is copied from the shipped-tree run
above; no result is reported that I did not produce.

---

## D1 — `get_report` reads any report by id, across tenants

* **What it is.** `get_report` fetched `SELECT * FROM reports WHERE id = ?` and returned the row
  and its snapshot with no tenant check at all (shipped `service.py:152-174`).
* **Impact.** Any authenticated actor — including a viewer in another tenant — could read the
  full payload and content hash of every report in the system by id. The id is the only secret;
  ids are returned by `save_report` and by the tenant-wide listing, so this is a straightforward
  horizontal privilege escalation across tenants.
* **Evidence.** `test_get_report_in_other_tenant_is_not_found` →
  `AssertionError: NotFound not raised`; `test_get_report_never_returns_another_tenants_snapshot`
  → `AssertionError: {'id': 'a92812d3…', 'tenant_id': 't1', …, 'payload': {'secret': 't1-only'}}
  is not None : cross-tenant read returned content`;
  `test_foreign_tenant_error_is_indistinguishable_from_missing_object` →
  `AssertionError: NotFound not raised`.
* **Fix.** After the row is found, `require_tenant(actor, row["tenant_id"])`
  (`service.py:178`). `require_tenant` raises `NotFound("no such object")` — the same type and
  message as the missing-object path — so a foreign report is indistinguishable from a
  non-existent one and nothing is disclosed about the other tenant.
* **Test.** `TestTenantIsolationReads` — `test_get_report_in_other_tenant_is_not_found`,
  `test_foreign_tenant_error_is_indistinguishable_from_missing_object` (asserts equal exception
  type *and* message for foreign vs missing id), `test_get_report_never_returns_another_tenants_snapshot`.

## D2 — `revoke_report` is exists-by-id only: no tenant scope, no role gate

* **What it is.** `revoke_report` looked the report up by id and immediately updated it; no
  tenant check and no role check (shipped `service.py:196-207`).
* **Impact.** Any actor, including a viewer or a foreign tenant admin, could revoke — i.e.
  destroy the availability of — any report in the system, and the audit row was written with the
  victim's `tenant_id`, so the trail attributed the action to the wrong tenant.
* **Evidence.** `test_cross_tenant_revoke_is_not_found`, `test_cross_tenant_revoke_error_matches_missing_object`
  → `AssertionError: NotFound not raised`; `test_non_owner_non_admin_may_not_revoke` →
  `AssertionError: Forbidden not raised`.
* **Fix.** `require_tenant(actor, row["tenant_id"])` first (the `NotFound` never discloses
  existence), then owner-or-admin: `actor.id == row["owner_id"]` requires a recognised role,
  otherwise `require_role(actor, "admin")` (`service.py:230-236`). The audit row now records
  `actor.tenant_id`, matching the reference feature.
* **Test.** `TestRevocationAuthorization` — `test_cross_tenant_revoke_is_not_found` (also asserts
  the report is *not* revoked afterwards), `test_cross_tenant_revoke_error_matches_missing_object`,
  `test_tenant_admin_may_revoke_any_report_in_the_tenant`, `test_owner_may_revoke_without_admin_role`,
  `test_non_owner_non_admin_may_not_revoke` (viewer and analyst, both denied, and the report is
  still readable).

## D3 — `get_report` never consults the classification

* **What it is.** Classification was stored but only surfaced in the returned dict; no check was
  made before returning the payload (shipped `service.py:162`).
* **Impact.** A `confidential` report was readable by every member of the tenant, directly
  contradicting "classified reports are readable only by tenant admins".
* **Evidence.** `test_confidential_report_is_admin_only` →
  `AssertionError: Forbidden not raised`; `test_confidential_read_is_forbidden_not_not_found` →
  `AssertionError: Forbidden not raised`.
* **Fix.** `may_read_classification(actor, row["classification"])` before the snapshot is read,
  raising `Forbidden` the same way `DatasetRegistry.get_dataset` does (`service.py:180-181`).
* **Test.** `TestClassification` — `test_confidential_report_is_admin_only`,
  `test_admin_may_read_confidential`, `test_confidential_read_is_forbidden_not_not_found`,
  `test_confidential_report_is_hidden_from_the_tenant_list`.

## D4 — `authz.require_role` fails open for an unrecognised role

* **What it is.** `if actor.role in ROLE_LEVEL and role_level(actor.role) < role_level(minimum)`
  — when the role was not in `ROLE_LEVEL` the whole condition was false and no exception was
  raised, so the guard became a no-op (shipped `authz.py:8-12`).
* **Impact.** Every role check in the package was bypassable by presenting a role string the
  build does not recognise (`"superuser"`, `"root"`, `"ADMIN"`, `""`, or `None`). With the
  tenant/classification checks also broken, that made an unknown role the most powerful
  principal in the system: it could save, read, list and revoke anything.
* **Evidence.** `test_unknown_role_is_denied_on_every_entry_point` reported
  `AssertionError: ReportCoreError not raised` for every (role, entry point) pair — 30 subtest
  failures across `'', '   ', 'superuser', 'root', 'ADMIN', None` × five entry points;
  `test_unrecognised_role_on_the_dataset_feature_is_denied_too` →
  `AssertionError: ReportCoreError not raised`.
* **Fix.** `require_role` refuses any role that is not recognised before comparing ranks:
  `if not is_known_role(actor.role): raise Forbidden(...)`, where `is_known_role` is a new
  one-line helper in the same module (`authz.py:8-26`). Denial is now the default for anything
  unrecognised, and the existing rank comparison is unchanged for real roles.
* **Test.** `TestFailClosedRoles.test_unknown_role_is_denied_on_every_entry_point` (empty,
  whitespace, wrong case, invented and `None` roles across all five entry points),
  `test_unknown_role_saves_nothing`, `test_unknown_role_never_reads_a_report_in_its_own_tenant`,
  `test_unrecognised_role_on_the_dataset_feature_is_denied_too`,
  `test_known_roles_still_work` (guards against over-blocking).

## D5 — `save_report` takes the tenant from the caller's payload

* **What it is.** `tenant_id = str(payload.get("tenant_id") or actor.tenant_id)` (shipped
  `service.py:134-135`).
* **Impact.** A caller could file a report into any tenant by putting `tenant_id` in the payload
  — planting content in a victim tenant, and (combined with D1) choosing a tenant whose members
  could then read it. Ownership was also attacker-influenced (`owner_id` in the payload was
  ignored in the row but the payload was stored verbatim in the snapshot).
* **Evidence.** `test_payload_tenant_id_cannot_move_a_report` →
  `AssertionError: 't2' != 't1'` (row stored under `t2`);
  `test_moved_report_is_not_readable_from_the_claimed_tenant` →
  `AssertionError: NotFound not raised` (the intruder in `t2` could read the moved report).
* **Fix.** `tenant_id = actor.tenant_id` and `owner_id = actor.id` (`service.py:153-154`), and the
  INSERT uses those values. Payload fields never decide tenant, owner or permissions (README
  convention 6); the payload is still stored unmodified as report content.
* **Test.** `TestProvenance` — `test_payload_tenant_id_cannot_move_a_report`,
  `test_payload_owner_id_cannot_reassign_ownership`, `test_tenant_and_owner_come_from_the_actor`,
  `test_moved_report_is_not_readable_from_the_claimed_tenant`, plus
  `TestBatchTruth.test_batch_cannot_launder_a_cross_tenant_item`.

## D6 — `list_reports` lists every tenant and reports revocation as `False`

* **What it is.** The query had no `WHERE tenant_id = ?`, no classification filter, and every row
  was emitted with a hard-coded `"revoked": False` (shipped `service.py:176-194`).
* **Impact.** Two leaks in one call: (a) a directory of every report name, id, classification and
  owner id in every tenant, and (b) a false status — already-revoked reports were presented as
  live, so a consumer would act on content the tenant had withdrawn. Confidential reports were
  listed to non-admins as well.
* **Evidence.** `test_list_reports_is_tenant_scoped` →
  `AssertionError: Lists differ: ['one', 'two'] != ['one']`;
  `test_list_reports_does_not_name_other_tenants_reports` → `[{'id': '86fba4d2…', …}] != []`;
  `test_list_reports_reports_revocation_truthfully` → `AssertionError: False is not true`;
  `test_confidential_report_is_hidden_from_the_tenant_list` →
  `AssertionError: Lists differ: ['closed', 'open'] != ['open']`.
* **Fix.** `WHERE tenant_id = ?` scoped by `actor.tenant_id` (`service.py:203`), rows filtered
  through `may_read_classification` (`service.py:219`), and `"revoked": r["revoked_at"] is not None`
  (`service.py:218`) so the flag mirrors the stored state.
* **Test.** `test_list_reports_is_tenant_scoped`, `test_list_reports_does_not_name_other_tenants_reports`,
  `test_list_reports_reports_revocation_truthfully`,
  `test_confidential_report_is_hidden_from_the_tenant_list`.

## D7 — `save_report` skips classification validation and the write role gate

* **What it is.** This defect is not labelled in the shipped source; it is visible by comparing
  `save_report` with the reference `DatasetRegistry.save_dataset`, which the same module says it
  follows. `save_report` called `_validate_name` and `_validate_payload` but never
  `_validate_classification`, and it performed no `require_role` at all.
* **Impact.** Two fail-open paths. (a) Any classification string was accepted and persisted; a
  report stored as `"public"` or `""` is not `"confidential"`, so `may_read_classification` treats
  it as the least sensitive content — a way to park material under a label the authorization code
  does not understand. (b) With no role gate, a viewer — and, because of D4, any unrecognised role
  — could create reports, so "an unknown, empty or unrecognised role is denied everywhere" could
  not hold for the write path.
* **Evidence.** `test_unrecognised_classification_is_rejected_on_save` →
  `AssertionError: ValidationError not raised` (for `'', 'public', 'top-secret', 'Internal', None`);
  `test_unvalidated_classification_cannot_be_stored` → `AssertionError: 1 != 0` (a row whose
  classification is outside `CLASSIFICATIONS` was persisted);
  `test_analyst_cannot_create_a_confidential_report` → `AssertionError: Forbidden not raised`.
* **Fix.** `classification = _validate_classification(classification)` (`service.py:145`) and the
  same gate as `save_dataset`: `require_role(actor, "analyst")`, plus `require_role(actor, "admin")`
  when the classification is `confidential` (`service.py:148-150`). The `analyst` minimum mirrors
  the reference feature exactly; the admin gate keeps `confidential` content admin-created as well
  as admin-readable.
* **Test.** `test_unrecognised_classification_is_rejected_on_save`,
  `test_unvalidated_classification_cannot_be_stored`, `test_analyst_cannot_create_a_confidential_report`,
  and `TestBatchTruth.test_wholly_invalid_batch_saves_nothing_and_says_so` (an item with
  `classification="bogus"` is not saved).

## D8 — `save_batch` swallows failures and reports a batch that never happened

* **What it is.** Per-item exceptions were caught and discarded, and the return value was
  `{"applied": len(items), "saved": saved, "status": "complete"}` — the requested item count, and
  `complete` unconditionally (shipped `service.py:209-226`).
* **Impact.** The caller was told every item was saved when some (or all) had failed, and
  `applied` disagreed with both the length of `saved` and the number of rows in the database. A
  caller that trusts the response would report success for content that does not exist, and would
  not retry the failed items.
* **Evidence.** `test_partial_batch_reports_the_truth` → `AssertionError: 3 != 2` (claimed 3,
  saved 2); `test_applied_matches_rows_actually_persisted` → `AssertionError: 4 != 2`;
  `test_wholly_invalid_batch_saves_nothing_and_says_so` → `AssertionError: 2 != 0`;
  `test_batch_cannot_launder_a_cross_tenant_item` → `AssertionError: 1 != 0`.
* **Fix.** Per-item isolation is kept (that part is intended for a batch API) but failures are no
  longer counted as successes: the loop counts what was appended, and the result is
  `{"applied": len(saved), "saved": saved, "status": "complete" if len(saved) == len(items) else "partial"}`
  (`service.py:246-271`). Non-object items and non-list `items` are rejected with `ValidationError`
  rather than raising an incidental `AttributeError`.
* **Test.** `TestBatchTruth` — `test_partial_batch_reports_the_truth`,
  `test_applied_matches_rows_actually_persisted` (compares `applied` against the row count in the
  database), `test_saved_ids_are_all_really_there`, `test_complete_batch_is_reported_complete`,
  `test_wholly_invalid_batch_saves_nothing_and_says_so`, `test_batch_cannot_launder_a_cross_tenant_item`.

## D9 — `may_read_classification` fails open on reads

* **What it is.** The read primitive returned `True` for anything that was not literally
  `"confidential"`, with no check that the actor's role was recognised at all
  (shipped `authz.py:15-19`). D4 and D9 are the same class of bug on the two halves of the
  package: the write guards and the read guard.
* **Impact.** A user with an empty, `None` or invented role could read every `internal` report in
  its tenant, and any object whose classification string was not exactly `"confidential"` (see D7)
  was treated as the least sensitive tier. "Denied everywhere (fail closed)" did not hold on any
  read path, including `get_report` and `list_reports`.
* **Evidence.** `test_unknown_role_never_reads_a_report_in_its_own_tenant` →
  `AssertionError: {'id': '4c8a3e85…', 'tenant_id': 't1', …, 'payload': {'secret': 1}} is not None`;
  `test_unknown_role_saves_nothing` → `AssertionError: 6 != 0`;
  `test_unknown_role_is_denied_on_every_entry_point` reported `ReportCoreError not raised` for the
  `get_report` and `list_reports` subtests.
* **Fix.** `may_read_classification` returns `False` for an unrecognised role and only `True` for
  a classification the build knows, and it keeps the existing `confidential` ⇒ admin rank check
  (`authz.py:29-40`). `get_report` raises `Forbidden` on the result; `list_reports` omits the row.
  An unrecognised role therefore sees no object and no listing at all, exactly as
  `DatasetRegistry` behaves.
* **Test.** `test_unknown_role_never_reads_a_report_in_its_own_tenant`,
  `test_unknown_role_saves_nothing`, `test_unknown_role_is_denied_on_every_entry_point`
  (the `get_report`/`list_reports`/`save_batch` subtests assert "no object, no rows, nothing
  saved"), `test_confidential_report_is_admin_only`.

---

## Audit coverage (requirement: every mutation and privileged read is audited)

The shipped code did write audit rows for `report.save`, `report.read`, `report.list` and
`report.revoke`, and the corrected code keeps that, with two corrections: the revoke and read
rows now carry `actor.tenant_id` instead of the victim object's tenant (D2, D3), and a refused
cross-tenant operation writes nothing, so the trail cannot be poisoned by an attacker aiming at
another tenant. Verified by `TestAudit` (`test_save_read_list_revoke_are_audited`,
`test_audit_rows_carry_actor_and_tenant`, `test_batch_writes_are_audited_per_item`) and, during
adversarial probing, by confirming no `report.revoke` row is written by a refused cross-tenant
revoke.

## Deliberately not changed

* **`Conflict` is imported but unused** in `service.py`. The plausible use would be refusing a
  second revocation of an already-revoked report. The brief does not require it, and revocation is
  currently idempotent with a stable snapshot; adding a new failure mode was out of scope. Left as
  imported, no behaviour invented.
* **An actor whose `tenant_id` is empty.** `require_tenant` already treats empty as
  not-a-member on every read, so such an actor can create but never read back. The `User` object
  is documented as authenticated and trusted input, so validating it is the authentication
  layer's job, not the service's. Not changed.
* **Denied attempts are not audited.** The reference feature `DatasetRegistry` audits successes
  only; adding denial auditing would be a new logging policy rather than a fix to a defect.
* **`DatasetRegistry` was left untouched** (its only changed dependency is `authz.py`). Its
  behaviour is unchanged for real roles and is now fail-closed for unrecognised ones; the
  regression coverage is `test_dataset_feature_still_roundtrips`,
  `test_unrecognised_role_on_the_dataset_feature_is_denied_too` and the original smoke test.

## Files

* `src/reportcore/authz.py` — D4, D9 (`is_known_role` helper; `require_role` and
  `may_read_classification` now fail closed).
* `src/reportcore/service.py` — D1, D2, D3, D5, D6, D7, D8; class docstring updated to describe
  the reviewed behaviour.
* `tests/test_authz_negative.py` — 39 negative authorization tests added (new file).
* `tests/test_smoke.py`, `run_checks.sh`, `README.md`, `CLAIMS.md`, `BRIEF.md`,
  `src/reportcore/{__init__,errors,models,store}.py` — unchanged (hashes verified against
  `.bench-fixture-baseline.json`).
