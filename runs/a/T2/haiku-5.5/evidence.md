# Evidence: files and lines inspected

All paths are relative to this directory. Commands were run here; outputs summarised below.

## Files read in full (line numbers as printed by `nl -ba`)

- web/users.js
  - 2-15: `api.listUsers()` does `GET /api/users` and returns `r.json()` unchanged (so it returns `{"users":[...]}`, an object, not an array).
  - 7-14: `api.setRole(id, role)` POSTs `{role}` only. No `version` is sent. The response body is returned but never checked for `error`.
  - 17-25: `roleOptions()` builds the option list from a hard-coded `['viewer','analyst','admin']`.
  - 30: `for (const user of await api.listUsers())` iterates the object returned at line 5. This is the bug that stops rendering (see Runtime checks).
  - 33-37: the row keeps `user.email`, `user.id`, `user.role`. `user.version` is never stored.
  - 38: comment states the intent: "Saving on change keeps the screen simple: no Save button to forget to press."
  - 39-42: `select.addEventListener('change', ...)` calls `api.setRole` immediately. Nothing checks the result. Line 41 writes "Saved." unconditionally. On failure the dropdown keeps the new value and the screen claims success.
  - 49: `render()` with no error handling.
- web/users.html
  - 10-15: table `#users`, 14: `<tbody id="rows">`. 16: `<p id="status" role="status">`. No Save/Cancel controls exist.
  - 17: loads `users.js`.
- src/adminaccess/app.py
  - 11: `WEB` path. 12: module-level `STORE = Store()`.
  - 13-14: seeds `u1` (ana, viewer, t1) and `u2` (bo, analyst, t1).
  - 15: `ACTOR = Actor(id="admin1", tenant_id="t1", role="admin")`. This is a constant. No authentication or session exists; every request acts as this admin.
  - 16: `SERVICE = UserService(STORE)`.
  - 43-44: `GET /api/users` returns `{"users": SERVICE.list_users(ACTOR)}`.
  - 48-59: `POST /api/users/<id>/role`. Reads `role` and `version` from the JSON body (54-55) and calls `change_role`. Any exception returns HTTP 400 with `{error: <ExceptionName>, message}` (56-58). So `StaleVersion`, `Forbidden` and `NotFound` all return 400.
  - 59: success returns 200 `{"user": row}`.
  - 68: binds `127.0.0.1:8099`.
- src/adminaccess/users.py
  - 9: `ROLES = ("viewer", "analyst", "admin")`.
  - 12-29: exception classes `Error`, `ValidationError`, `Forbidden` (20-21), `NotFound`, `StaleVersion`.
  - 20-21: `Forbidden` is defined but never raised anywhere in the code (checked by reading all of users.py and app.py).
  - 32-36: `Actor(id, tenant_id, role)`. The `role` field is never read by the service.
  - 43-47: `get_user` checks the tenant (line 45).
  - 49-54: `list_users` is tenant-scoped (line 51-52) and returns `id, email, role, version`.
  - 56: `change_role(actor, user_id, new_role, seen_version=None)`. Docstring: "Persist a role change immediately."
  - 58-59: validates `new_role` against `ROLES`.
  - 60-62: loads the row, raises `NotFound` on missing row or cross-tenant row (line 61).
  - 63-64: optimistic check, only when `seen_version is not None`. Raises `StaleVersion`.
  - 65-68: `UPDATE users SET role=?, version=version+1 ...`. No commit here.
  - 69: `self.store.audit(...)` with action `user.role_change`, detail `"old->new"`. `audit()` commits, so the UPDATE and the audit row commit together.
  - 70: returns `get_user(...)`.
  - No check on `actor.role` anywhere in `change_role`. No check that the new role differs from the old one, so a no-op still bumps the version and writes an audit row.
- src/adminaccess/store.py
  - 8-25: `users` table has `version INTEGER NOT NULL DEFAULT 1` (line 14). `audit` table (17-25) with `actor_id, tenant_id, action, object_id, detail`.
  - 30-34: `Store(path=":memory:")`, row_factory set to `sqlite3.Row`.
  - 54-60: `audit()` inserts and commits (line 59-60).
- tests/test_smoke.py
  - 14-17: `svc()` fixture, one user u1 viewer, admin actor.
  - 21-23: `test_list_is_tenant_scoped`.
  - 25-29: `test_change_role_persists_and_audits`: calls `change_role(admin, "u1", "analyst")` with no version and asserts role `analyst` and version `2`. This test must keep passing, so `seen_version` must stay optional.
  - Note: the test name says "audits" but the test does not check the audit row. The audit requirement is currently untested.
- README.md
  - 16-21: design notes. Line 18: "`change_role()` writes straight through. The screen calls it on every dropdown change." Line 19-20: `version` is for optimistic concurrency. Line 21: each accepted change writes an audit row.
- run_checks.sh (2-4), run_app.sh (2-4), .bench-fixture-baseline.json (hash manifest; not modified by me).
- BRIEF.md: task definition.

## Commands run and results

1. `find . -type f` (excluding nothing): listed the files above. Only `src/adminaccess/` and `web/` contain code.
2. `sh run_checks.sh`: `Ran 2 tests ... OK`. Baseline is green.
3. Direct service probe, `PYTHONPATH=src python3 -c ...` using `SERVICE`, `ACTOR`, `STORE` from app.py:
   - `list_users` returned `{"users": [{id u1, role viewer, version 1}, {id u2, role analyst, version 1}]}`.
   - A `Actor(id='x', tenant_id='t1', role='viewer')` successfully changed u1 to `admin`, version 2. **A viewer-role actor can grant admin.** Confirms users.py:56-70 has no role check.
   - `change_role(ACTOR, 'u1', 'analyst', 1)` raised `StaleVersion: expected version 2, got 1`. Stale check works when a version is supplied.
   - audit table: `('x', 'user.role_change', 'u1', 'viewer->admin')`. Audit row written.
4. Live HTTP probe: `PYTHONPATH=src python3 -m adminaccess.app` on 127.0.0.1:8099, then curl:
   - `GET /api/users` returned the `{"users": [...]}` object (confirms the shape used by users.js line 5).
   - `POST /api/users/u1/role {"role":"analyst"}` returned 200 `{"user": {... "role":"analyst","version":2}}`. No version sent, so no stale check. Change applied with no confirmation step.
   - `POST ... {"role":"superuser"}` returned `{"error":"ValidationError", ...}`, HTTP 400.
   - `POST /api/users/nope/role {"role":"admin"}` returned HTTP 400 (NotFound mapped to 400).
5. Browser-logic probe with node 26.7.0 (`/home/sjeva/.hermes/tools/node-26.7.0-linux-x64/bin/node`): loaded web/users.js with a mocked `fetch` returning the real `{"users":[...]}` shape and a stub `document`. Output: `render threw: TypeError (intermediate value) is not iterable`. Confirms users.js:30 cannot iterate the API response, so the page renders no rows in its current form. The stub DOM is minimal, so this is a logic-level check, not a browser render. The probe script is at `/home/sjeva/bench/model-testing/hermes-home/cache/scratch/probe_render.js` (scratch dir, outside this directory, per runtime instructions).

## Runtime notes

- No files in the deliverable tree were modified. The only writes are `work-package.md` and this file. The fixture baseline file was read, not changed.
- The live server was started under `timeout 8` and exited on its own.
- Lightpanda was not used: the browser-logic gap was checked with node and a mocked DOM, which is sufficient for the render-path finding but does not prove visual behaviour in a real browser.
