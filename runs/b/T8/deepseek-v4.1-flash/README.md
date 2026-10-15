# reportcore

Multi-tenant knowledge/report backend used by the OpenJM tenant portal. Pure stdlib
(sqlite3 + unittest), no third-party dependencies.

## Layout

```
src/reportcore/errors.py    exception types
src/reportcore/models.py    User/Tenant dataclasses, role ranks, classifications
src/reportcore/store.py     sqlite schema + Store wrapper (the only DB access point)
src/reportcore/authz.py     role and tenant checks
src/reportcore/service.py   DatasetRegistry (reference feature) + SavedReportsService
tests/                      visible smoke tests
run_checks.sh               python3 -m unittest discover -s tests -v
```

## Conventions (follow these)

1. Validate input in the service before touching the store; raise `ValidationError`.
2. Gate by role with `authz.require_role(actor, minimum)` where `minimum` is
   `viewer` < `analyst` < `admin`.
3. Scope **every** query by `actor.tenant_id`. A foreign tenant is a `NotFound`, never a
   `Forbidden`: errors must not disclose that an object exists elsewhere.
4. Immutable content is stored as canonical JSON plus a sha256 digest. Revocation flips a
   status column; it never edits or deletes the stored snapshot.
5. Write one audit row per mutation and per privileged read via `store.add_audit(...)`.
   Actions are `"<object>.<verb>"`, e.g. `dataset.save`, `report.revoke`.
6. `User` is authenticated and trusted; anything in a `payload` is caller-controlled and
   must never decide tenant, owner or permissions.

## Run

```sh
sh run_checks.sh
```
