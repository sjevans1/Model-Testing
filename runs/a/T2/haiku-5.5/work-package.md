# Work package: stage and confirm role changes in the admin console

Scope: stop the role dropdown from writing to the API on every change. Changes are staged in the browser, applied only by an explicit Save, discarded by Cancel, and enforced on the server. No redesign: same two endpoints, same tables, same Python stdlib stack.

Evidence references (file:line) are in evidence.md. Line numbers below refer to the current repository.

## 1. What changes, and where

Files to change:

1. src/adminaccess/users.py (change_role, lines 56-70)
   - Add the server-side authorization check. Actor.role (line 36) is currently never read. Require `actor.role == "admin"`, else raise the existing `Forbidden` class (lines 20-21, currently never raised). Check order inside change_role: (1) Forbidden if actor is not admin, (2) validation of new_role (58-59), (3) row lookup and tenant check / NotFound (60-62), (4) stale version (63-64), (5) UPDATE and audit (65-69). The role check comes first so a non-admin never reads or writes; this is the single authoritative order (section 4 matches it).
   - No-op guard: if `new_role == row["role"]`, return the current row without bumping version or writing audit. Rationale: the UI will never send a no-op after this change, but a double-click or a retry should not create audit noise. (Optional; see section 9.)
   - Keep the optional `seen_version` parameter (line 56). Keep the existing stale check (63-64) as is.
   - Add the audit write only on an applied change (already happens at line 69; keep it after the UPDATE).

2. src/adminaccess/app.py (do_POST, lines 48-59; Handler error mapping 56-58)
   - Map exceptions to status codes instead of always 400:
     - Forbidden -> 403 `{"error": "Forbidden", "message": ...}`
     - StaleVersion -> 409 `{"error": "StaleVersion", ...}`
     - NotFound -> keep 400 (today's behaviour; changing it is out of scope)
     - ValidationError -> keep 400
   - Keep the body shape `{"error", "message"}` unchanged.
   - Leave line 15 (`ACTOR` constant) alone. See section 4 for why this is a known gap, not something to fix here.

3. web/users.js (api at 2-15, render at 27-49)
   - Fix the pre-existing bug at line 30: `api.listUsers()` returns `{"users": [...]}` (app.py:44), but render() iterates it as an array. Change line 30 to iterate `(await api.listUsers()).users`. Do not change the server response shape; other callers would break.
   - Remove the `change` listener (lines 39-42) that calls setRole on every change.
   - Store per row: `applied = {role, version}` taken from the list response (version is returned by list_users, users.py:51). Store `staged = applied.role` on change; do not call the API.
   - Render a Save button and a Cancel button per row, enabled only when staged !== applied.role. Disable both while a request is in flight.
   - Save: POST `{role: staged, version: applied.version}` to the existing endpoint (api.setRole, lines 7-14; extend it to accept and send `version`). On 200: set applied from `body.user` (role and version), clear staged, set status to "Saved." (line 41 today; keep the text). On 409: discard staged, re-fetch the list, set status "Changed by someone else; reloaded. Please review and try again." On 403: revert select to applied.role, set status "You do not have permission to change roles." On 400 or network error: keep the staged value and show the error text (`body.message` or "Could not save. Try again."), so the user can retry or cancel.
   - Cancel: set select back to applied.role, clear staged, no request, status "Changes discarded."
   - Only write "Saved." after a 200. Today line 41 writes it unconditionally, even when the server fails.

4. web/users.html (table header line 12; no structure change beyond one column)
   - Add `<th>Actions</th>` to the header row at line 12 and one `<td>` per row in users.js. Keep the `aria-label` on the select (users.js:36) and the `#status` element (line 16).

5. tests/test_smoke.py: add the tests in section 6. Do not edit the two existing tests (lines 21-23 and 25-29).

6. tests/test_http.py (new file, stdlib only): exercise the HTTP layer. Used for the 403/409 mapping in section 6. Start `app.Handler` on `127.0.0.1` port 0 in a thread, post with urllib, then shut down. Note that app.py creates `STORE`/`SERVICE` at import time (app.py:12-16); the test must use those module globals, or the test must construct its own Handler binding. Simplest: import `adminaccess.app` and use `app.SERVICE`, `app.ACTOR` as-is, and assert on the returned status codes and the DB state via `app.STORE`.

7. README.md (lines 18-21): update the design note on line 18 ("writes straight through ... on every dropdown change") to say changes are staged in the UI and applied on Save. Update the line 19-20 note to say the UI sends `version` on every Save.

Why these boundaries: the authorization and version logic live in users.py, which is the only place the database is written. The HTTP layer only maps errors to codes. The UI owns staging, which is presentational. Nothing outside these files is touched.

Not in these files: store.py (schema unchanged, see section 8), run_app.sh, run_checks.sh, BRIEF.md, the fixture baseline file.

## 2. State transition

States per user row (client-side), backed by server state:

- Server state: `role_s`, `version_s` (users table, store.py:13-14).
- Client applied: `applied = {role, version}` from the last list or successful save.
- Client staged: `staged` (null when no pending change).

Transitions:

1. Load: applied = list row (role, version). staged = null.
2. Select change to X != applied.role: staged = X. No request. Save/Cancel enabled.
3. Select change back to applied.role: staged = null. Save/Cancel disabled.
4. Save with staged = X:
   - Request: POST /api/users/<id>/role {role: X, version: applied.version}.
   - Server applies atomically (users.py:65-69): role = X, version = version + 1, one audit row. Response 200 with the updated row.
   - Client: applied = {role: X, version: row.version}, staged = null, status "Saved.".
5. Save fails:
   - 403 Forbidden: server state unchanged. Client: staged = null, select reverts to applied.role, status message as in section 1.
   - 409 StaleVersion: server state unchanged. Client: staged = null, re-fetch list, status message. The user re-selects if still wanted.
   - 400 ValidationError or NotFound: server state unchanged. Client keeps staged so the user can correct or cancel.
   - Network error or 5xx: server state unknown from the client's view. Client keeps staged and shows "Could not save. Try again." Retry sends the same version; if the server did apply it, the retry gets 409 and the client reloads. That is the correct outcome.
6. Cancel: staged = null, select reverts. No request.

Invariant: the server role changes only through a successful POST with a matching version. Staged values never leave the browser.

## 3. Save/Apply and Cancel/Discard semantics

- Apply is per row. Each row has its own Save and Cancel. No global "Save all" in this package (keeps the diff small; a global apply is a redesign).
- Save is the only action that issues a write.
- Cancel discards staged changes for that row only. It does not reload other rows.
- Navigating away or refreshing with staged changes discards them. No beforeunload prompt in this package (optional follow-up).
- A failed Save never clears the server-side state and never shows "Saved.".
- Status text must be produced only from the result of a request, never before it.

## 4. Stale updates and authorization

Stale updates:
- The service already supports optimistic concurrency: `change_role` raises StaleVersion when `seen_version != row.version` (users.py:63-64). The UI must now always send `version` (the value from the list or last save). Without it the server accepts blind writes (users.py:63 only checks when not None).
- Server behaviour on stale: 409, no write, no audit row (the check at 63-64 happens before the UPDATE and audit).
- The UI reloads on 409 (section 1, item 3).
- Compatibility: `seen_version` stays optional at the service level so test_change_role_persists_and_audits (tests/test_smoke.py:25-29) still passes unchanged. The HTTP layer must not reject a missing version in this package (see section 9, decision D1).

Server-side authorization (required):
- Requirement: only an actor with role `admin` in the same tenant may change a role. Tenant scope is already enforced (users.py:61). Add the role check: `if actor.role != "admin": raise Forbidden("admin role required")`. Place it before the DB read so a non-admin probe does not reveal which users exist (keep NotFound first only for cross-tenant, which is already tenant-scoped; the order is: role check, then lookup).
  - Decision: check role before lookup. Then a non-admin always gets 403, and cross-tenant behaviour is unchanged for admins.
- Why the frontend cannot be the boundary: any HTTP client can POST to /api/users/<id>/role. This was demonstrated in evidence.md (step 4 and the service probe in step 3): a `viewer` actor successfully changed u1 to `admin` at the service layer, and curl can post directly. Hiding a control or disabling a select in users.js does not stop a request. The check must be in users.py.
- Known gap, not fixed here: app.py:15 hard-codes `ACTOR = Actor(id="admin1", ... role="admin")` and there is no authentication. Every HTTP request acts as admin. The new role check protects the service API and any future caller that passes a real Actor, but it does not protect the HTTP endpoint today. Closing this needs an authentication design and is out of scope. This must be stated in the release notes and must not be described as "access control is now enforced" for the HTTP surface.

## 5. Audit expectation

For every applied change (200 response):
- Exactly one row in `audit` (store.py:17-25) with: actor_id = actor.id, tenant_id = actor.tenant_id, action = `user.role_change`, object_id = user_id, detail = `"<old>-><new>"` (existing format, users.py:69).
- Written in the same transaction as the UPDATE. Currently `audit()` commits (store.py:59-60) after the UPDATE which is not committed separately (users.py:65-69). Keep that ordering; do not add a second commit between them.
- Not audited: forbidden attempts, stale rejections, validation errors, and no-ops (section 1 no-op guard). Failed attempts being audited is a reasonable follow-up but changes the audit contract; out of scope here.

## 6. Regression tests to add

tests/test_smoke.py, new methods in TestUserService. Do not change existing methods.

1. test_viewer_actor_cannot_change_role
   - Actor(id="v1", tenant_id="t1", role="viewer"); change_role on u1 to "admin".
   - Expect Forbidden. Assert u1 role still "viewer" and version still 1, and no new audit row.
2. test_analyst_actor_cannot_change_role: same with role "analyst"; Forbidden.
3. test_stale_version_is_rejected_without_write
   - change_role(admin, "u1", "analyst", seen_version=1) succeeds (version -> 2); then change_role(admin, "u1", "admin", seen_version=1) must raise StaleVersion. Assert role remains "analyst", version 2, and audit count unchanged from after the first change.
4. test_current_version_applies: change_role(admin, "u1", "analyst", seen_version=1) returns version 2, role analyst.
5. test_invalid_role_does_not_write: change_role(admin, "u1", "superuser") raises ValidationError; role and version unchanged; no audit row.
6. test_cross_tenant_actor_gets_not_found: Actor(tenant_id="t2", role="admin") on u1 -> NotFound; no write, no audit.
7. test_applied_change_writes_one_audit_row: after one change, audit has exactly one `user.role_change` row with actor_id "admin1", tenant_id "t1", object_id "u1", detail "viewer->analyst". (This closes the gap noted in evidence: the existing test name says "audits" but does not check.) Note: adding this assertion inside a new test, not by editing the old one.
8. test_noop_change_does_not_bump_version_or_audit (only if decision D2 accepted): change to same role returns version 1, no audit row.

tests/test_http.py (new):
9. test_post_forbidden_returns_403: call the handler path for a non-admin. Because app.py hard-codes ACTOR, this test must patch `adminaccess.app.ACTOR` to a viewer Actor (use unittest.mock.patch) for the request; assert HTTP 403 and body error "Forbidden"; assert DB unchanged.
10. test_post_stale_version_returns_409: post `{"role":"analyst","version":99}`; assert 409, body error "StaleVersion", DB unchanged.
11. test_post_valid_version_returns_200_and_new_version: post `{"role":"analyst","version":1}`; assert 200 and body user.version == 2.
12. test_post_validation_still_400: post `{"role":"superuser"}`; assert 400 (regression guard on existing behaviour).

Use a fresh Store for the HTTP tests, not the module-level STORE, by patching `adminaccess.app.SERVICE` with a `UserService(Store())` seeded with u1. Tests must not depend on order.

UI tests: no JS test runner exists. Add tests/test_users_js.js that loads web/users.js in node with a mocked fetch and DOM (the probe in evidence.md step 5 is the starting point) and asserts: (a) rendering a list of `{users:[...]}` produces one row per user; (b) changing the select does not call fetch with POST; (c) Save posts `{role, version}`; (d) Cancel posts nothing. Wire it into run_checks.sh only behind `command -v node >/dev/null 2>&1`, printing a skip line otherwise. Node must not become a hard requirement.

Manual browser check (required before sign-off, since mocked DOM is not a real render): run_app.sh, open http://127.0.0.1:8099/, confirm rows render, change a select, confirm no request in devtools network until Save, confirm Save shows "Saved.", confirm a forced 409 (open two tabs, change in one, Save stale in the other) reloads and shows the message.

## 7. Migration and compatibility risks

- Response shape for GET /api/users is unchanged (`{"users": [...]}`). The UI fix at users.js:30 is client-side only. Do not change the API to return an array; that would break any other consumer.
- HTTP error codes change for Forbidden (new, 403) and StaleVersion (400 -> 409). Any client that treats all 4xx the same is unaffected. A client that parses `error` names is unaffected because the body shape is kept. A client that depended on StaleVersion returning 400 would break. None exists in this repository (checked: only web/users.js calls the endpoint). Flag in release notes.
- Clients that POST without `version`: still accepted (decision D1). They bypass optimistic concurrency, as they do today.
- Existing rows: no schema change. Version and audit tables are unchanged. No data migration.
- Existing audit rows: unchanged.
- Users who relied on "change applies immediately": this is the intended behaviour change. Communicate in release notes: role changes now require Save.
- Authorization turns on a new denial: any caller that previously passed a non-admin Actor to change_role will now get Forbidden. In this repository only app.py:15 constructs an Actor (admin), so no existing path breaks. Verify with grep before merging.
- Known: no authentication; the HTTP role check is effectively unconditional admin today (section 4).

## 8. Exact acceptance conditions

All must hold:

1. `sh run_checks.sh` passes, including the original two tests unchanged (test_smoke.py:21-23 and 25-29 diff-identical to the baseline) and the new tests in section 6.
2. The new authorization test (items 1-2) fails on the current code (demonstrating the gap) and passes after the change. Record this in the implementation notes.
3. users.py `change_role` raises Forbidden for a non-admin actor before any UPDATE; grep confirms `Forbidden` is raised.
4. app.py maps Forbidden -> 403, StaleVersion -> 409; ValidationError and NotFound still 400.
5. users.js: no fetch with method POST occurs on select change (verified by test and by devtools in the manual check).
6. users.js: "Saved." is only written after a 200 response.
7. Manual browser check (section 6) passes.
8. store.py is unchanged (schema, version column, audit table). Verify with a diff.
9. GET /api/users response shape unchanged: `{"users": [{id, email, role, version}]}`, tenant-scoped.
10. README.md design notes updated (lines 18-20) to match behaviour.
11. No new third-party dependency. stdlib only; node is optional for the JS test.

## 9. Stop conditions

Stop and report (do not work around) if:

- Making `change_role` check the role breaks test_change_role_persists_and_audits (tests/test_smoke.py:25-29). That test uses the admin actor, so it should pass; if it does not, the check is wrong.
- The fix would require changing the GET response to an array, or changing the schema in store.py.
- The fix would require authentication, sessions, or changes to how ACTOR is built, beyond the role check. That is a redesign; stop and escalate.
- Making version required at the HTTP layer breaks an existing caller found in the repo. (Decision D1 says do not make it required; if a reason emerges, stop.)
- A test in run_checks.sh has to be edited, skipped, or retargeted to get green. Forbidden by the brief.
- The manual browser check cannot be run. Report it as not done; do not claim the UI is verified.

Open decisions (recommended defaults; the implementer should follow these unless told otherwise):

- D1: `version` stays optional at the HTTP layer for compatibility. The UI always sends it. Default: optional.
- D2: No-op same-role save returns 200 without version bump or audit. Default: accepted. If rejected, skip test item 8 and leave behaviour as is.
- D3: Forbidden attempts are not audited. Default: not audited, follow-up item.
- D4: Only `admin` may change roles, including self-demotion. No self-demotion guard in this package. Default: no guard; flag as follow-up.

## 10. Must remain unchanged

- Endpoint paths and methods: GET /api/users, POST /api/users/<id>/role, GET / and /users.html, GET /users.js.
- GET /api/users response shape and tenant scoping (users.py:49-54; app.py:43-44).
- Role list ROLES = ("viewer", "analyst", "admin") (users.py:9) and the set of valid roles (users.py:58-59).
- Schema in store.py (tables, columns, defaults; version starts at 1; version increments by 1 per applied change).
- Audit row format and action name `user.role_change` with detail `old->new` (users.py:69).
- Behaviour of change_role for an admin actor with no seen_version: applies, bumps version, writes audit, returns row (test_smoke.py:25-29 must pass unchanged).
- Tenant isolation: cross-tenant ids still return NotFound (users.py:61).
- Error body shape `{"error", "message"}` (app.py:57).
- 400 for ValidationError and NotFound (app.py:56-58).
- Seed data in app.py:13-14 and ACTOR at app.py:15.
- Bind address and port 127.0.0.1:8099 (app.py:68), run_app.sh, run_checks.sh (except the optional node line in section 6).
- The `#status` element and its aria-live role (users.html:16), the aria-label on each select (users.js:36).
- Files outside the list in section 1, the fixture baseline file, BRIEF.md.
