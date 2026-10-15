# Saved Reports — implementation notes

Deliverable: `SavedReportsService` in `src/reportcore/service.py`, tests in
`tests/test_saved_reports.py`, this file.

## First full test run

`sh run_checks.sh` was run once after implementing the four methods, before any
correction cycle: **32 tests, OK, exit 0** (2 pre-existing smoke tests + 30 new).
No correction cycle was needed; no existing test was edited, skipped or retargeted.
`tests/test_smoke.py` is byte-identical to the shipped file (verified against
`.bench-fixture-baseline.json`: sha256 prefix `8fdb273ff4213577`).

## Design decisions

1. **Immutable snapshot next to the report row.** `save_report` writes the `reports`
   row and the `report_snapshots` row in one `with self.store.conn:` transaction
   (the same pattern `DatasetRegistry.save_dataset` uses for
   `datasets` + `dataset_versions`). The snapshot is
   `_canonical(payload)` — the module-level helper already in the file:
   `json.dumps(sort_keys=True, separators=(",",":"), default=str)` plus
   `sha256` of the UTF-8 blob. The digest is also the audit `detail`, exactly as
   `dataset.save` records it. There is no update path for the snapshot: nothing in
   the service ever writes `report_snapshots` again.

2. **Tenant and owner come from the actor only.** The inserts use
   `actor.tenant_id` / `actor.id`; the payload is stored verbatim as content. A
   payload carrying `tenant_id`/`owner_id` keys is *not* rejected (it is legitimate
   report content) but those keys never influence the row — covered by
   `test_save_takes_tenant_and_owner_from_actor_not_payload`. This follows README
   convention 6.

3. **Validation before authorization, before the store.** Order mirrors
   `DatasetRegistry.save_dataset`: `_validate_name` → `_validate_payload` →
   `_validate_classification` → `require_role(actor, "analyst")`, with
   confidential content additionally requiring `admin`. Every query is scoped by
   the actor's tenant. Nothing is written when validation or authorization fails,
   so no audit row and no partial state appear.

4. **Role gates.** `analyst` for `save_report` (confidential additionally `admin`)
   and for `revoke_report`; `viewer` may read/list internal content. Unknown roles
   rank 0 in `role_level` and fail closed. Confidential reads are `admin`-only
   (`authz.may_read_classification`), and listing filters the same way.

5. **Cross-tenant = NotFound.** `get_report` and `revoke_report` load the row by id
   (missing → `NotFound`), then `require_tenant(actor, row["tenant_id"])` *before*
   the classification check, so a foreign confidential report is indistinguishable
   from a nonexistent one — a foreign tenant can never produce `Forbidden`.
   `list_reports` filters `WHERE tenant_id = ?`. Failed attempts write no audit row,
   as in `DatasetRegistry`.

6. **Revocation is a status flip.** `revoke_report` only updates
   `revoked_at`/`revoked_by`/`revoke_reason` on `reports`; the `report_snapshots`
   row is untouched, so the payload, canonical JSON and content hash remain
   readable and byte-identical (`test_revoke_flips_status_without_touching_the_snapshot`
   compares the whole snapshot row before/after). A revoked report stays retrievable
   and remained listed, with `status == "revoked"`, so history stays auditable.
   Revoking an already-revoked report raises `Conflict` (the only error type in
   `errors.py` unused by `DatasetRegistry`; it also guards against silently
   rewriting the original revocation record). Un-revocation is not offered — not
   requested by the brief, and adding it would mutate provenance.

7. **Audit.** One row per mutation and per privileged read, via
   `store.add_audit`, using the documented `"<object>.<verb>"` form:
   `report.save` (detail = content hash), `report.revoke` (detail = reason),
   `report.read` and `report.list` (tenant scoped, `object_id` NULL for list).
   Rejected requests are not audited.

8. **Returned shapes.** `get_report` returns the report columns
   (`id`, `tenant_id`, `owner_id`, `name`, `classification`, `created_at`) plus
   `content_hash`, the decoded `payload`, and the revocation view (`status`,
   `revoked_at`, `revoked_by`, `revoke_reason`). `list_reports` returns tenant-scoped
   summaries (`id`, `tenant_id`, `owner_id`, `name`, `classification`, `created_at`,
   `revoked_at`, `status`) without payloads, mirroring how `list_datasets` avoids
   returning content. `payload` is re-decoded per call, so mutating a returned dict
   cannot alter stored state.

## How to reproduce the verification

```sh
cd /home/sjeva/bench/model-testing/runs/b/T3/deepseek-v4.1-flash
sh run_checks.sh
```

Expected: `Ran 32 tests ... OK`, exit status 0. To run only the new suite:

```sh
PYTHONPATH=src python3 -m unittest tests.test_saved_reports -v
```

Standalone check of the snapshot hash (independent of the unit tests):

```sh
PYTHONPATH=src python3 - <<'EOF'
import hashlib, json
from reportcore import SavedReportsService, Store, User
store = Store(); store.seed_tenant("t1", "One")
alice = User(id="u1", tenant_id="t1", email="a@t1", role="analyst")
rid = SavedReportsService(store).save_report(alice, "R", {"b": 1, "a": 2})
row = store.fetchone("SELECT * FROM report_snapshots WHERE report_id = ?", (rid,))
blob = json.dumps({"b": 1, "a": 2}, sort_keys=True, separators=(",", ":"))
print(row["payload_json"])
print(row["content_hash"] == hashlib.sha256(blob.encode()).hexdigest())
EOF
```

## Scope

Only `src/reportcore/service.py` was modified (plus the two new deliverable files);
every other tracked file's hash still matches the baseline manifest. No dependency
outside the standard library was used, and nothing outside this directory was
touched.
