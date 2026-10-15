# T8 — SavedReports acceptance test plan

Subject: `src/reportcore/service.py::SavedReportsService` as shipped in this directory.
Author's claims: `CLAIMS.md`. Conventions the module is written against: `README.md`
("Conventions"), with `DatasetRegistry` in the same file as the reference implementation.

Nothing under `src/` was modified and `tests/test_smoke.py` was not touched — verified by
re-computing the fixture baseline hashes (sha256[:16] of every file listed in
`.bench-fixture-baseline.json` still matches, see "Constraints respected" at the end).

## 1. How to run

    PYTHONPATH=src python3 -m unittest discover -s tests        # the suite (stdlib only)
    PYTHONPATH=src python3 -m unittest discover -s tests -v     # per-test names
    python3 tests/mutation_check.py                             # mutation evidence (~3 min)
    python3 tests/mutation_check.py --only M8                   # one mutation
    python3 tests/mutation_check.py --keep                      # keep the scratch copies

`tests/mutation_check.py` is a tool, not a test: discovery collects only `test*.py`, so the
official command never runs it.

## 2. Result on the shipped tree

    $ PYTHONPATH=src python3 -m unittest discover -s tests
    Ran 70 tests ... FAILED (failures=31, errors=1)

70 test methods: 43 pass, 27 fail (unittest counts 31 failures + 1 error because
`subTest` cases are reported individually). Reproduced 5 times in a row with an identical
result; the concurrency test was additionally run 12 times on its own (12/12 stable).

Failing methods, by module (all 27 are expected — see §4 for why each one is a genuine
violation rather than a bad test):

| module | failing / total |
|---|---|
| `test_claim1_permissions.Claim1Permissions` | 10 / 15 |
| `test_claim2_snapshot_integrity.Claim2SnapshotIntegrity` | 3 / 14 |
| `test_claim3_batch_reporting.Claim3BatchReporting` | 8 / 12 |
| `test_inputs_and_authorization.InputValidation` | 1 / 5 |
| `test_inputs_and_authorization.RoleGates` | 5 / 5 |
| `test_duplicates_and_concurrency` | 0 / 4 |
| `test_dataset_registry_regression` | 0 / 9 |
| `test_smoke.py` (pre-existing, untouched) | 0 / 1 |

Verdict: **claim 1 is false, claim 2 is only half-true, claim 3 is false.**

* Claim 1 (permission safety) — false on every clause: the read path is not tenant scoped,
  classification is never consulted, and a caller-supplied `payload["tenant_id"]` decides
  the owning tenant of a new report (`service.py:135`). The list view returns every tenant's
  reports.
* Claim 2 (revocation never changes the stored snapshot) — the *storage* half holds: no test
  could make the snapshot change under revocation (§4, M12/M15 show the tests do bite when
  the snapshot is touched). What fails is the surrounding permission contract: revocation
  has neither a role gate nor a tenant scope, and `list_reports` reports every revoked
  report as un-revoked (`service.py:188`), i.e. the historical state is misreported even
  though the bytes are intact.
* Claim 3 (batch truth) — false: per-item failures are swallowed and the batch always
  returns `{"applied": len(items), "status": "complete"}` (`service.py:222-226`). A batch of
  three items with one invalid item returns `applied: 3 / complete` while only 2 rows exist.
* `DatasetRegistry` does not regress (9/9 green) — but `authz.require_role` fails *open* for
  an unrecognised role (`authz.py:11`), which is reachable through the reference feature too
  (`RoleGates.test_unknown_role_fails_closed_everywhere`).

A red suite is the intended outcome: the brief requires that each test fail when the claim
it covers is false, and the claims are false as shipped. The suite is not "supposed" to be
green here; the mutation harness below shows it goes green on a repaired implementation.

## 3. Where "truth" comes from (no echo-chamber assertions)

Every claim-level assertion compares the service's answer against something the service
does not produce:

* raw rows read through `Store` (`report_snapshots.payload_json` / `content_hash`,
  `reports.tenant_id`, `audit` rows, `COUNT(*)`) — `support.py`;
* a content hash recomputed by the test from the payload it itself submitted
  (`support.content_hash`, canonical JSON, sha256) rather than copied from a return value;
* the snapshot *fingerprint* (the two stored strings) captured before the operation and
  compared byte-for-byte afterwards;
* a positive control on every "must not see it" sweep (`surfaces(...)`), so a sweep that
  silently sees nothing at all fails instead of passing.

`subTest` is used for the invalid-input tables so that every bad value is reported
separately.

## 4. The three claims, clause by clause

Legend: "detect" = what makes the test fail.

### Claim 1 — permission safety (`tests/test_claim1_permissions.py`, 15 tests)

| test | clause | detect |
|---|---|---|
| `test_owner_tenant_member_roundtrips_the_report` | normal operation | payload/tenant/owner/name/classification/hash must all come back as submitted |
| `test_same_tenant_viewer_may_read_an_internal_report` | internal is tenant-readable | a viewer read must succeed |
| `test_privileged_read_is_audited_against_the_owning_tenant` | README 5 | exactly one `report.read` row, with actor and owning tenant |
| `test_foreign_tenant_member_cannot_read_the_report` | "readable only by members of the owning tenant" | a foreign `get_report` must raise `NotFound` |
| `test_foreign_tenant_error_does_not_disclose_existence` | README 3 | foreign and non-existent ids must raise the *same* exception type; the id must not appear in the message |
| `test_foreign_tenant_confidential_read_is_not_found_not_forbidden` | README 3 ordering | `NotFound`, never `Forbidden`, for a foreign confidential report |
| `test_read_surface_never_surfaces_a_foreign_report` | "a report **and its snapshot**" | every public read entry point, for 3 foreign actors, must not hand back the id — with a positive control on the owner |
| `test_confidential_report_is_readable_only_by_tenant_admins` | "confidential reports only by tenant admins" | viewer/analyst → `Forbidden`; admin → payload |
| `test_payload_tenant_id_cannot_move_a_report` | "cannot move a report into another tenant by supplying a tenant id" | stored row tenant, returned tenant, foreign read and foreign listing must all stay `t1` |
| `test_payload_tenant_id_cannot_forge_the_audit_tenant` | README 6 | the `report.save` audit row's tenant must be the actor's |
| `test_list_reports_is_tenant_scoped` | tenant scoping | each tenant sees exactly its own row |
| `test_list_reports_hides_confidential_from_non_admins` | "only by tenant admins" | confidential id absent for viewer, present for admin |
| `test_list_reports_does_not_leak_payloads` | "and its snapshot" | a payload marker must not appear in the list view |
| `test_listing_is_audited` | README 5 | exactly one `report.list` row |
| `test_denied_read_does_not_write_to_the_store` | no side effects on denial | row counts unchanged after a denied read |

### Claim 2 — snapshot immutability (`tests/test_claim2_snapshot_integrity.py`, 14 tests)

| test | clause | detect |
|---|---|---|
| `test_save_stores_canonical_json_and_matching_sha256` | README 4 | stored blob must equal the canonical JSON, hash must equal the independently recomputed sha256 |
| `test_equal_payloads_hash_equal_whatever_the_key_order` | canonical form | two dicts with the same content but different insertion order must hash equal |
| `test_revoke_leaves_the_stored_snapshot_byte_identical` | "revocation never changes the stored snapshot" | stored (payload_json, content_hash) bytes unchanged; returned payload/hash unchanged and still equal to the recomputed hash; `revoked` true |
| `test_revoke_neither_deletes_nor_duplicates_the_snapshot` | same | row counts stay 1/1, the snapshot row still exists |
| `test_revoked_report_is_still_readable_to_the_owning_tenant` | revocation is a flag, not a delete | a viewer can still read the historical payload |
| `test_history_is_stable_across_repeated_reads_after_revocation` | "the historical content hash is stable" | 5 reads must agree with each other and with the recomputed hash |
| `test_repeated_revocation_does_not_mutate_the_snapshot` | conflicting update | see §6 — the snapshot must be untouched whether the second revocation is accepted or rejected |
| `test_snapshot_is_not_aliased_between_two_reports_with_equal_content` | duplicate submissions | revoking one must not revoke (or rehash) the other |
| `test_revoke_requires_an_admin_role` | README 2, task bullet "role changes and revocation" | viewer/analyst → `Forbidden`, and the rejected call must not be half-applied |
| `test_foreign_tenant_cannot_revoke_and_existence_is_not_disclosed` | tenant scoping | foreign revoke → `NotFound`, target still un-revoked |
| `test_revoke_of_an_unknown_report_is_not_found` | invalid input | `"0"*32`, `""`, `None` → `NotFound` |
| `test_revoke_writes_exactly_one_audit_row` | README 5 | one `report.revoke` row, correct actor/tenant |
| `test_list_reports_reports_revocation_state_truthfully` | "correct reporting" | the revoked row must be listed `revoked: true`, the other `false` |
| `test_revocation_does_not_change_the_stored_payload_bytes` | independent second check | raw JSON string equality, not just parsed equality |

### Claim 3 — batch truth (`tests/test_claim3_batch_reporting.py`, 12 tests)

| test | clause | detect |
|---|---|---|
| `test_all_valid_batch_reports_complete_and_the_true_count` | "status is `complete` only when every item was saved" | `complete`, `applied == 3`, `len(saved) == 3`, 3 rows in the store |
| `test_every_saved_id_is_readable_and_carries_the_right_content` | correct reporting | each returned id resolves, payloads match, no duplicate ids, a snapshot exists per id |
| `test_empty_batch_saves_nothing_and_does_not_crash` | boundary | 0 applied, empty list, no rows (status deliberately not pinned, see §7) |
| `test_partial_batch_is_not_reported_as_complete` | "complete **only** when every item was saved" | status must differ from `complete` for one rejected item |
| `test_partial_batch_count_equals_what_was_actually_saved` | "the count it returns is the count that was actually saved" | `applied == len(saved) == rows in store`; the two saved names are the right ones |
| `test_partial_batch_does_not_persist_the_rejected_item` | failed operations reported as such | exactly one row, and not the rejected name |
| `test_batch_of_only_invalid_items_never_reports_them_as_saved` | failed/partial | either the call is refused or `applied == 0` and status ≠ `complete`; 0 rows either way |
| `test_batch_with_a_malformed_item_never_over_reports` | failed input | a non-object item is never counted as saved |
| `test_mixed_malformed_and_valid_batch_reports_partial_truthfully` | mixed failure | accounted-for count matches the store; status ≠ `complete`; nothing but the valid item persisted |
| `test_batch_items_cannot_choose_their_tenant` | claim 1 via the batch path | rows are the actor's tenant, foreign read `NotFound`, no rows in `t2` |
| `test_batch_item_cannot_grant_itself_a_higher_classification` | unauthorised access | an analyst's confidential item is not saved and is not counted |
| `test_batch_requires_authorisation_like_a_single_save` | unauthorised access | a viewer's batch persists nothing and does not report saves |

## 5. Supporting areas

`tests/test_inputs_and_authorization.py` (15 tests)
`InputValidation` — name must be a non-empty string (5 bad values), payload must be an
object (5 bad values), classification must be one of `CLASSIFICATIONS` (6 bad values, incl.
`None`), the name is trimmed, unknown report ids are `NotFound`. Every invalid request is
also checked to have written no `reports`/`report_snapshots` row.
`RoleGates` — saving needs ≥ analyst, confidential creation needs an admin, an unknown role
fails closed on all three paths (report save, confidential read, dataset save), a demotion
takes effect on the next call and a demoted admin loses confidential read.
`PayloadCannotEscalate` — `owner_id`/`role`/`tenant_id`/`classification` in the payload
change nothing; one snapshot per save.
`FixturesAreSane` — two assertions that protect the harness itself.

`tests/test_duplicates_and_concurrency.py` (4 tests) — identical submissions produce two
independent reports (2 rows, 2 snapshots, equal hashes, distinct ids), revocation state is
not shared, a batch of three identical items saves three, and a threaded run
(3 readers × 25 reads against 1 revoker × 3 revocations on a file-backed sqlite store, one
connection per thread) must produce no exception, no torn read (every observation must
carry the original hash and payload), a single surviving snapshot and at least one audit
row. Verified stable across 12 consecutive isolated runs.

`tests/test_dataset_registry_regression.py` (9 tests) — pins the reference feature:
roundtrip, foreign-tenant `NotFound`, version immutability, role/confidential gates,
validation before the store, confidential read, scoped+filtered listing, audit pair,
and that datasets and reports do not share rows. All green on the shipped tree.

## 6. Mutation evidence — proof that the tests bite

`tests/mutation_check.py` never edits this tree. For each case it copies the repo into a
scratch directory, applies the patch(es), and runs the official command there. Every patch
anchor must match exactly once or the harness aborts, so a patch that silently does nothing
cannot be mistaken for "the mutation was not detected".

Two questions are answered:

1. **Are the tests satisfiable?** `REPAIRED` applies all seven fixes for the defects the
   shipped tree contains (D1–D6, D8 + the shared `require_role` fail-open). Result:

       PASS  REPAIRED      70 tests ran, 0 failing

   So the suite is not unsatisfiable, over-specified or self-contradictory: an
   implementation that fixes exactly the seeded defects passes every one of the 70 tests.

2. **Does each test detect the failure it claims to detect?** 17 seeded defects were
   introduced one at a time into the repaired copy. Result — **19 cases, 0 failed
   expectations**:

| mutation | seeded defect | tests killed (of the named expectations) |
|---|---|---|
| `SHIPPED` | the tree as delivered | 27 methods, incl. all 24 named expectations |
| `M1_get_report_without_tenant_scope` | `get_report` ignores the tenant | 7, incl. `test_foreign_tenant_member_cannot_read_the_report`, `..._read_surface_never_surfaces_a_foreign_report` |
| `M2_get_report_ignores_classification` | classification never consulted | 3, incl. `test_confidential_report_is_readable_only_by_tenant_admins` |
| `M3_revoke_without_role_check` | no role gate on revocation | 2, incl. `test_revoke_requires_an_admin_role` |
| `M4_revoke_without_tenant_scope` | no tenant scope on revocation | 1, `test_foreign_tenant_cannot_revoke_and_existence_is_not_disclosed` |
| `M5_payload_decides_tenant` | payload chooses the tenant | 3, incl. `test_payload_tenant_id_cannot_move_a_report` |
| `M6_list_reports_not_scoped` | list returns every tenant | 3, incl. `test_list_reports_is_tenant_scoped` |
| `M7_list_reports_hardcodes_not_revoked` | list always says `revoked: false` | 1, `test_list_reports_reports_revocation_state_truthfully` |
| `M8_batch_swallows_failures` | batch lies about count/status | 7, incl. `test_partial_batch_is_not_reported_as_complete`, `..._count_equals_what_was_actually_saved` |
| `M9_unknown_role_fails_open` | `require_role` skips unknown roles | 1, `test_unknown_role_fails_closed_everywhere` |
| `M10_save_without_role_gate` | no role gate on save | 5, incl. `test_saving_requires_at_least_analyst` |
| `M11_save_does_not_validate_classification` | classification not validated | 1, `test_classification_must_be_a_known_value` |
| `M12_revoke_rewrites_the_snapshot` | revocation rewrites `payload_json` | 4, incl. `test_revoke_leaves_the_stored_snapshot_byte_identical` |
| `M13_revoke_by_content_hash` | revocation updates every row sharing the hash | 3, incl. `test_snapshot_is_not_aliased_between_two_reports_with_equal_content` |
| `M14_non_canonical_content_hash` | hash over unsorted JSON | 7, incl. `test_equal_payloads_hash_equal_whatever_the_key_order` |
| `M15_revoke_deletes_the_snapshot` | revocation drops the snapshot row | 11, incl. `test_revoke_neither_deletes_nor_duplicates_the_snapshot` |
| `M16_store_shares_one_connection_per_path` | one sqlite connection per path shared by all threads | 1, `test_concurrent_revocations_and_reads_leave_a_consistent_report` |
| `M17_privileged_read_not_audited` | no audit row for a read | 1, `test_privileged_read_is_audited_against_the_owning_tenant` |

Three of these deserve a note:

* `M12`/`M15` are the honest test of claim 2. The shipped code happens to satisfy the
  immutability clause, so on this tree those tests are green; the mutations show they are
  not vacuous (a rewritten or deleted snapshot is caught, byte for byte).
* `M16` is the only way to falsify the threaded test, and it is exactly its purpose: the
  test's failure mode is a crash/lock/torn read, not a wrong return value. It was also
  shown stable (12/12) on the unmutated tree, so it is not flaky.
* `M13` covers "duplicate submissions" beyond row counts: a plausible real-world defect is
  revoking by content hash, which would silently revoke unrelated duplicates.

The remainder of the killed-on-`SHIPPED` list is not an accident: every failing method on
the shipped tree is killed by at least one of the individual mutations, i.e. each failure is
attributable to a seeded defect that the repair removes.

## 7. Deliberate ambiguities and coverage gaps

Deliberate ambiguities. Where the contract does not pin the behaviour down, the test
asserts only what the claims require and says so in a docstring, instead of inventing a
rule:

* repeat revocation (`test_repeated_revocation_does_not_mutate_the_snapshot`,
  `...concurrent...`): the tests allow either "accepted and idempotent" or "rejected with a
  `ReportCoreError`", and only require that the snapshot is unchanged, the report still
  revoked and no snapshot row is duplicated/lost;
* an entirely malformed batch (`test_batch_of_only_invalid_items...`,
  `...malformed_item...`, `...mixed_malformed...`): rejecting the whole request with
  `ValidationError`, or returning an honest partial summary, are both accepted; claiming
  success is not;
* the empty batch does not pin `status` (the claim's "every item was saved" is vacuous for
  zero items);
* an unknown role's *listing* view is not asserted (only its read/save paths);
* the exact `status` vocabulary for a partial batch is not pinned — only `!= "complete"`.

Known gaps:

1. **No optimistic-concurrency token exists in the API.** Reports have no version column
   and no `if-match`-style parameter, so a genuine lost-update conflict cannot be provoked
   through the service; §4's "conflicting update" tests cover the observable consequences
   (snapshot stability, no aliasing, honest reporting) and thread-level corruption. A
   future `Conflict`-raising update path would need its own tests.
2. **Concurrency is single-process, thread-based, one host.** No multi-process, WAL or
   network-latency interleavings, and no ordering assertions (the only ordering guarantee
   used is `ORDER BY name`).
3. **Storage-layer backstop is absent.** The schema declares `REFERENCES tenants(id)` but
   sqlite foreign-key enforcement is off by default and the store never enables it, so
   nothing below the service would catch a tenancy bug like D5. These tests therefore prove
   service-layer behaviour only; a caller that writes with raw SQL is out of scope.
4. **The batch summary's failure detail is not specified.** The repaired implementation
   returns a `failed` list, but no test requires it (the claim only fixes the count and the
   status), so an implementation can under-inform *which* items failed. This is recorded as
   a specification gap, not as a passing test.
5. **Delete/retention, re-classification, renaming and re-ownership do not exist** in the
   API and are consequently untested; if they are added, the immutability and permission
   tests here are the template.
6. **Authentication is out of scope** by design: `User` is trusted (README 6). No test
   attempts to forge an identity, only a payload.
7. **Audit completeness is only asserted for the paths the README names** (one row per
   mutation and per privileged read). *Denied* attempts are not required to be audited, so
   no test demands it; if that becomes a requirement, the `audit` table already has what is
   needed.
8. **The read-surface sweep is a fixed list** (`support.read_surface`). A new public read
   method would have to be added there to be covered; the positive control keeps the sweep
   honest in the meantime.
9. **No coverage measurement** is reported: `coverage` is a third-party package and the
   brief forbids installing anything. Test-to-clause mapping in §4 is the substitute.

## 8. Constraints respected

* `src/` untouched and `tests/test_smoke.py` untouched — every file listed in
  `.bench-fixture-baseline.json` still hashes to its recorded sha256[:16] after this work.
* The suite is stdlib-only (`unittest`, `sqlite3`, `hashlib`, `json`, `threading`,
  `tempfile`), no network, no third-party imports, and it runs with the official command.
* Nothing pre-existing was weakened, skipped, retargeted or deleted. `run_checks.sh` (which
  runs the whole suite verbosely) now exits non-zero on this tree; that is the finding
  reported in §2, not a change to any check.
* Scratch trees used by the mutation harness are created under `TMPDIR`
  (`.../hermes-home/cache/scratch/t8-mutation-*`) and removed unless `--keep` is given.
