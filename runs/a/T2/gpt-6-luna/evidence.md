# Evidence inspected

These are the supplied files and line ranges inspected before preparing `work-package.md`:

- `BRIEF.md:37-58` — instruction to read implementation first, required work-package contents, and stop condition not to implement the change.
- `README.md:1-14` — repository layout, runtime stack, and file responsibilities.
- `README.md:16-21` — documented current behavior: immediate role writes, per-user optimistic `version`, and `user.role_change` audit on accepted changes.
- `web/users.js:1-15` — current list/mutation fetch calls and POST body currently containing only `role`.
- `web/users.js:17-25` — existing role options and role selection initialization.
- `web/users.js:27-49` — list rendering, current immediate POST on dropdown change, success message, and render call.
- `web/users.html:9-18` — existing user table, rows target, live status area, and script inclusion.
- `src/adminaccess/store.py:8-25` — existing users/audit schema, including `version`, audit actor/tenant/action/object/detail fields.
- `src/adminaccess/store.py:29-44` — SQLite connection, schema initialization, and query helpers.
- `src/adminaccess/store.py:46-60` — user insertion and audit insertion/commit behavior.
- `src/adminaccess/users.py:9-30` — allowed role constants and existing service exceptions, including `Forbidden` and `StaleVersion`.
- `src/adminaccess/users.py:32-37` — `Actor` fields: id, tenant, and role.
- `src/adminaccess/users.py:39-54` — service initialization, tenant-scoped get, and list returning `id`, `email`, `role`, and `version`.
- `src/adminaccess/users.py:56-70` — current role validation, tenant-scoped target lookup, optional pre-read version check, update, audit, and returned row.
- `src/adminaccess/app.py:8-16` — service setup and hard-coded demo `ACTOR`.
- `src/adminaccess/app.py:19-26` — JSON response helper.
- `src/adminaccess/app.py:28-46` — static page/js routes and list response envelope `{ "users": [...] }`.
- `src/adminaccess/app.py:48-61` — role POST route, payload handling, optional version forwarding, blanket exception-to-400 handling, and success envelope `{ "user": row }`.
- `tests/test_smoke.py:8-17` — test import/setup and tenant-scoped service fixture.
- `tests/test_smoke.py:20-30` — existing tenant-list and role-persistence/version smoke tests.
- `run_checks.sh:1-4` — repository test command.
- `run_app.sh:1-4` — app launch command; inspected for repository context, not changed.
- `src/adminaccess/__init__.py` — inspected; empty file.

Commands actually run:

- `./run_checks.sh` — failed with exit code 126 (`Permission denied`; script is not executable in this sandbox).
- `sh run_checks.sh` — passed: 2 tests ran, both passed (`test_change_role_persists_and_audits`, `test_list_is_tenant_scoped`).

No application code, tests, or existing checks were changed. Only `work-package.md` and this evidence report were created.