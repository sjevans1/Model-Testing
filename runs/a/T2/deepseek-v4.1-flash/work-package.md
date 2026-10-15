# Work package — role changes must be staged, confirmed, authorised and version-guarded

Target: the `adminaccess` admin-console slice in this directory
(`src/adminaccess/{app,store,users}.py`, `web/users.{html,js}`, `tests/test_smoke.py`).
Every file+line reference below was read in this working directory; every claim marked *verified*
has a command and an observed output in `evidence.md`. Nothing here is inferred from a summary.

Defect (as reported): `web/users.js` POSTs a role change the moment the administrator picks a
different option, so the access level changes with no confirmation step. Support has seen accidental
privilege changes.

Defect (as measured): reproduced end-to-end. One `change` event on the Role select produced exactly
one `POST /api/users/u1/role`, persisted `viewer -> admin` (version 1 -> 2) and displayed `Saved.`
with no button pressed (`evidence.md` E6). The handler that does this is `web/users.js:39-42`:

```js
select.addEventListener('change', async () => {
  await api.setRole(user.id, select.value);            // <- write on selection
  document.getElementById('status').textContent = 'Saved.';
});
```

Two related defects sit on the same code path and are covered here because they cannot be separated
from the fix (§8 R9/R10): the row loop never renders (`users.js:30`), and a rejected POST still
displays `Saved.` (`users.js:41`).

## 0. Scope

In scope: staging + explicit apply/discard in `web/users.js`; the minimum markup in
`web/users.html` to host those controls; the server-side authorisation gate and the atomic version
check in `src/adminaccess/users.py`; new regression tests.

Out of scope: no new endpoints, no request/approval workflow, no schema change, no HTTP status-code
change, no framework, no dependency, no polling, no client-side persistence of staged state, no
change to `change_role`'s immediate-apply contract. Two deferred items are listed in §9.

## 1. What changes, in which files, and why those are the right boundaries

| # | File | Change | Why this is the right boundary |
|---|---|---|---|
| 1 | `web/users.js` | Replace the auto-POST handler (`users.js:39-42`) with per-row staging and explicit Apply/Cancel controls; make `api.setRole` (`users.js:7-14`) send `version`; iterate the response envelope in the row loop (`users.js:30`); report real failures instead of always writing `Saved.` (`users.js:41`). | The premature write lives *only* here. `users.js:38` states the intent it was written for ("Saving on change keeps the screen simple: no Save button to forget to press") — the fix removes that trade-off, not the screen. No other file decides *when* a change is transmitted. |
| 2 | `web/users.html` | Add one `<th>` for the new action cell (`users.html:12`); keep everything else, in particular `<p id="status" role="status" aria-live="polite">` (`users.html:16`) as the single message target. | Rows gain two controls, so the table needs a third column. Reusing `#status` avoids inventing a second alerting mechanism and preserves the existing accessibility contract. |
| 3 | `src/adminaccess/users.py` | (a) Raise the already-declared but never-raised `Forbidden` (`users.py:20-21`) at the top of `change_role` (`users.py:56`) when the actor may not administer access. (b) Replace the check-then-act version comparison with a guarded UPDATE (§4.3). Nothing else changes. | `users.py:1` states the contract ("Authorization here is the real boundary; the UI is not"), and `change_role` is the only place holding the `Actor` (`users.py:32-36`) and performing the write (`users.py:63-69`). A guard here covers every caller; a guard in `app.py` would be a second, weaker copy. The read-modify-write at `users.py:60-68` is exactly where (b) belongs. |
| 4 | `tests/test_role_apply.py` *(new)* | The regression tests in §7. | `run_checks.sh` discovers `tests/`, so new coverage belongs there. `tests/test_smoke.py` stays byte-identical (Frozen, §10). |
| 5 | `README.md` | One sentence at `README.md:18` ("The screen calls it on every dropdown change.") becomes false once the screen stages instead. Correct that sentence only. | A design note that contradicts the code invites the next engineer to reintroduce the bug. Docs-only; not part of the acceptance criteria. |

Not changed: `src/adminaccess/store.py` (no schema change needed — `users.version` at `store.py:14`
and the `audit` table at `store.py:17-25` already do the job, which is what keeps this package
small) and `src/adminaccess/app.py` (`app.py` already forwards `payload.get("version")` at
`app.py:55`; its routing, its JSON error envelope at `app.py:57` and its 400-for-every-failure
behaviour are left exactly as they are — the UI branches on the `error` field instead).

Why no server-side "pending change" table: `change_role` applies immediately and returns the new row
(`users.py:70`), `README.md:18` documents write-through, and `tests/test_smoke.py:25-29` pins it
(`change_role(admin, "u1", "analyst")` -> `role == "analyst"`, `version == 2`). A two-phase server
workflow would break that test and rewrite the data model. Staging in the browser is the bounded fix.

Alternatives rejected: a `confirm()` dialog (still commits implicitly on OK, nothing to inspect or
discard); a second endpoint (duplicates authorisation and audit — a redesign); a client-only fix
(leaves the defect's root cause: the endpoint has no actor check, §5).

## 2. Intended state transition

Per row, three client-side values. Only one is client-authored.

| Value | Meaning | Source of truth |
|---|---|---|
| `applied` | the role the server last confirmed for this user | `GET /api/users` on load, or `response.user.role` after a successful apply |
| `version` | the server version that `applied` corresponds to | `GET /api/users` on load, or `response.user.version` after a successful apply |
| `staged` | the option currently selected in the dropdown | the administrator |

Invariant: `applied` and `version` are only ever written from a server response, never from local
intent. `staged` is the only value the client invents. `dirty := (staged !== applied)`.

Row state, derived from those three values: `clean` (nothing staged), `dirty` (staged differs from
applied, nothing in flight), `saving` (a request is in flight for this row), `conflict` (a
`StaleVersion` refresh left `staged !== applied`), `error` (a failed apply that left
`staged !== applied`).

```
              select a different option
  clean ────────────────────────────────▶ dirty              (no network call at all)
    ▲                                       │
    │ Cancel / Discard                      │ Apply
    └───────────────────────────────────────┤ POST {role: staged, version}
                                            ▼
                    ┌───────────────────────┴────────────────────────┐
                    │ 200                                            │ failure
                    ▼                                                ▼
  applied := response.user.role                    applied, version UNCHANGED
  version := response.user.version                 persisted role UNCHANGED
  staged  := null, state := clean                  staged: per §3.5-3.7
```

Failure rule the implementer must preserve: **on any failure the server's role for that user is
unchanged**, and the client must not present the staged value as applied. A failed Apply must never
render as success — today `users.js:41` writes `Saved.` unconditionally, which is provably wrong: a
rejected POST still displayed `Saved.` while the server row was unchanged (`evidence.md` E6).
(`fetch` rejects only on network errors; an HTTP 400 **resolves**, so the code must branch on
`response.ok`/the body's `error`, not on `try/catch` alone.)

## 3. Save/Apply and Cancel/Discard semantics (exact)

1. Selecting a different option sets `staged` and re-renders the row. **No request is sent.** The
   dropdown shows the staged value, so the administrator can see what they picked.
2. A row with `staged !== null && staged !== applied` is `dirty`: Apply and Cancel are enabled and
   the row carries a visible unsaved marker (e.g. `row.dataset.state = "dirty"` plus a text marker —
   not colour alone).
3. A row with `staged === null || staged === applied` is `clean`: both controls are disabled.
4. **Apply** is a `<button type="button">` with accessible name `Apply role change for <email>`
   (mirroring the existing `aria-label` pattern on the select, `users.js:36`). It sends exactly one
   `POST /api/users/<id>/role` with body `{"role": <staged>, "version": <version>}` and, for that
   row, disables the select and both controls until the response arrives, so a double click cannot
   produce a second POST.
5. Success (`200` with `user`): `applied = response.user.role`, `version = response.user.version`,
   `staged = null`, state `clean`, and `#status` reads exactly `Saved.` — the same string the screen
   uses today (`users.js:41`), so wording and the existing live-region behaviour are preserved.
6. `StaleVersion`: see §4.4.
7. `Forbidden`: nothing was changed server-side; `staged` is kept, the row is marked `error`, Apply
   stays **enabled** and `#status` says the signed-in account may not change access levels. The
   client deliberately does not disable the control: it cannot know the actor's authority
   (`GET /api/users` returns only id/email/role/version, `users.py:50-53`), and pretending to know
   would re-create the illusion that the UI is the boundary (§5). The server refuses again; that is
   correct.
8. `ValidationError` / `NotFound`: the server refused the value or the target outright, so `staged`
   is reverted to `applied` (`NotFound` additionally triggers a list refresh) and `#status` shows
   the server's `message` verbatim.
9. Unrecognised non-2xx, unparsable body, or a network error: `staged` is kept, Apply stays enabled,
   `#status` reads "Could not save the change. Try again." Nothing is claimed to have succeeded.
10. **Cancel** discards the staged value: `staged = null`, the select is set back to `applied`, the
    row returns to `clean`, `#status` is cleared. It sends **no** request and never rewrites the
    server — Cancel is a client-side discard, not a revert of a committed change.
11. Selecting again while dirty simply replaces `staged`; if it equals `applied` the row returns to
    `clean` and `#status` is cleared.
12. Reloading the page discards staged values. Staged state must **not** be persisted in
    `localStorage`/`sessionStorage`: a staged privilege grant must not survive a reload and reappear
    later.
13. SHOULD: a `beforeunload` guard while any row is dirty, so an accidental navigation cannot
    silently drop a staged change. Not part of the acceptance conditions; drop it if the reviewer
    wants the smallest possible diff.

## 4. Stale updates (`version`)

The mechanism already exists and must be used, not rebuilt.

### 4.1 What already works

* `users.version` is an integer, bumped on every applied write (`store.py:14`, `users.py:66`).
* `list_users` returns it per user (`users.py:50-53`) — *verified*: `{"id":"u1",...,"version":1}`
  (`evidence.md` E4/B1).
* `app.py:55` already forwards `payload.get("version")` into `change_role`.
* `change_role` rejects a mismatch with `StaleVersion` (`users.py:63-64`) — *verified*, and the HTTP
  layer surfaces it as `400 {"error":"StaleVersion","message":"expected version 2, got 1"}`
  (`evidence.md` E2/A3, E4/B4).
* The POST response returns the full refreshed row including the new version (`users.py:70`,
  `app.py:59`), so the client can update its cached version without a refetch.

### 4.2 The hole that makes it dead code today

The client never sends the version: `users.js:11` builds `{ role }` only, so `seen_version` arrives
as `None` and the guard at `users.py:63` is skipped entirely — every UI write is a blind
last-write-wins. *Verified*: a POST without `version` was accepted and bumped `version` 1 -> 2
(`evidence.md` E2/A4, E4/B2). Fixing this is the core of "how stale updates are handled".

### 4.3 The server must also make the comparison atomic (part of change 3)

`users.py:60-68` is a read-modify-write: SELECT, compare in Python, UPDATE. Ship the comparison and
the write as one statement so they cannot be separated:

```
# arm 1 — seen_version is None (unchanged, backward compatible: tests/test_smoke.py:27 depends on it)
UPDATE users SET role=?, version=version+1, updated_at=? WHERE id=?
# arm 2 — seen_version given
UPDATE users SET role=?, version=version+1, updated_at=? WHERE id=? AND version=?
if cursor.rowcount != 1: raise StaleVersion(...)
```

Pin it with a test that injects a competing write between the read and the write
(`test_concurrent_write_between_select_and_update_is_rejected`, §7.2) — with today's check-then-act
code that competing write is silently overwritten; with the guarded UPDATE it is refused.

Keep the tenant check (`users.py:60-62`) **ahead** of the UPDATE, so a foreign-tenant id still yields
`NotFound` rather than `StaleVersion`. `HTTPServer` is single-threaded (`app.py:68`) so this is not
currently exploitable, but a check-then-act guard for a permission write is the same class of defect
being fixed here, one layer down, and the fix is 3 lines.

### 4.4 Client behaviour on `StaleVersion`

1. Do **not** claim success and do **not** auto-retry: a blind re-POST would silently overwrite the
   colleague's change — the very defect this package exists to remove.
2. Re-read `GET /api/users`, take `applied` and `version` for that row from the server, and keep the
   administrator's `staged` value visible (it may still be what they want).
3. If `staged !== applied` after the refresh, mark the row `conflict` and have `#status` explain it,
   e.g. "This user's access was changed by someone else. Review the current role and apply again."
4. The refreshed `version` is what the next Apply echoes, so a retry after a conflict is a normal
   optimistic-concurrency retry.

(Alternative, also acceptable and simpler: discard `staged` on a conflict and reset the row to the
server's role. Pick one and state it in the code comment; the requirement is only that the
administrator is told and that nothing is auto-reapplied.)

### 4.5 Residual gap, carried deliberately

A versionless write (`seen_version is None`, `users.py:63`) is still accepted as last-write-wins.
This package does **not** close that at the HTTP layer: `tests/test_smoke.py:27` calls `change_role`
with no version and must keep passing, and making `version` mandatory would break any already-served
copy of `users.js` for the duration of a rolling deploy (`app.py:36-42` serves `users.js` with no
cache headers, so browser caches outlive a release). See Deferred D1 in §9 — a known limitation, not
an oversight.

Two tabs of the same screen each hold their own version; the second Apply gets `StaleVersion` and
reconciles per §4.4. That is the intended behaviour and is the most likely shape of the support
reports.

## 5. Server-side authorization (and why the frontend cannot be the boundary)

### 5.1 Required change

In `src/adminaccess/users.py`, in `change_role` (`users.py:56`), as the **first** statement of the
method body — before role validation (`users.py:58-59`), before the user lookup (`users.py:60-62`)
and before the version guard (`users.py:63-64`):

* If `actor.role != "admin"`, raise `Forbidden` — the type already declared at `users.py:20-21` and
  currently raised nowhere (grep over `src/`: the only occurrence of `Forbidden` is its definition).
* Nothing else in `change_role` changes: no signature change, no new exception type, no change to
  the returned row. Keep tenant scoping and role-enum validation exactly as they are.
* Do not build a permission model, roles table or policy engine. With the flat three-role vocabulary
  (`ROLES`, `users.py:9`), `actor.role == "admin"` is the whole rule.

Order is part of the requirement: authorising first means a non-admin cannot use the endpoint as an
oracle (no `NotFound` to probe whether a user id exists in the tenant, no `ValidationError` to probe
the role vocabulary, no `StaleVersion` to observe that someone else changed the row).

### 5.2 Why the frontend cannot be the boundary

1. **The endpoint is directly callable.** The screen is only one client of
   `POST /api/users/<id>/role` (`app.py:48-59`); a plain HTTP client reaches the same `change_role`
   call. Disabling or hiding a control in `users.js` removes the accident, not the ability.
2. **There is no check to rely on today.** `change_role` reads `actor.id` (`users.py:69`) and
   `actor.tenant_id` (`users.py:61`) but never `actor.role`. *Verified*: an `Actor(role="viewer")`
   in the right tenant successfully promoted a user to `admin` (`evidence.md` E2/A1). The tenant
   comparison at `users.py:45`/`users.py:61` is data scoping, not authority.
3. **`version` is a concurrency control, not an authorisation control** — a client may send any
   value for it.
4. **The service is the only place that holds the actor.** `app.py:15` fixes `ACTOR` server-side and
   `app.py:54` passes it in; the client never names the actor. Therefore the client cannot be trusted
   with the decision *and* does not need to supply anything. Do **not** add an
   `actor`/`role`/`is_admin` field to the POST body: anything the client can send, the client can
   forge.
5. **The service is the reusable boundary.** `users.py:1` and `README.md:18` declare it as such; a
   guard in the HTTP handler would sit inside the blanket `except Exception` at `app.py:56` and would
   leave any other `UserService` caller unguarded.
6. **The HTTP layer's actor is a fixture.** `app.py:15` hardcodes an `admin` actor; in production the
   actor must come from an authenticated session. Do **not** build that identity system here — only
   guarantee that whatever actor the HTTP layer supplies is checked. Consequence to accept
   knowingly: with the fixture's admin actor the new gate is invisible in the running app, which is
   why the service-level tests in §7.1 are mandatory evidence that it exists.

## 6. Audit expectation for an applied change

* Exactly **one** `audit` row per **applied** change, written by `change_role` itself at
  `users.py:69` -> `store.audit` (`store.py:54-60`), with `action = "user.role_change"`,
  `object_id` = the target user id, `actor_id`/`tenant_id` from the applying `Actor`, and
  `detail = "<old_role>-><new_role>"`. *Verified* against real rows:
  `user.role_change | u1 | viewer->analyst` (`evidence.md` E2/A5). Do not change the action string
  (`README.md:21` documents it) or the detail format.
* **No** audit row when the change is not applied: forbidden, stale, invalid role, unknown user, or
  a client-side Cancel/Discard (which never reaches the server). *Verified* for the stale path
  (`evidence.md` E2/A6).
* The audit row must be written only on the success path of the same code path that performs the
  UPDATE, never from the HTTP layer, never on rejection, and never with an actor identity taken from
  the request body.
* **Implementation hazard — verified, not hypothetical.** The `UPDATE` is not committed by itself;
  the commit that persists it is the one inside `store.audit()` (`store.py:60`). Measured: with
  `store.audit` replaced by a no-op, a second sqlite3 connection still saw the *old* role, i.e. the
  UPDATE never became durable (`evidence.md` E3). So: keep calling `store.audit(...)` on the success
  path; do not return between the UPDATE (`users.py:65-68`) and the audit call; and if any early
  return is ever added after the UPDATE, commit explicitly (`self.store.conn.commit()`) first. A
  dropped audit call silently loses *both* the audit trail and the privilege change — the exact
  failure this package is meant to prevent.
* Optional, additive, P2: append the version transition to `detail` (e.g. `viewer->analyst (v1->v2)`).
  *Verified* safe — no test asserts `detail` (`tests/test_smoke.py:25-29` assert only `role` and
  `version`) and nothing reads the `audit` table. Skip it if any downstream consumer parses the
  format. Not in this package's acceptance criteria.

## 7. Regression tests to add

New file `tests/test_role_apply.py` (stdlib `unittest` only). `tests/test_smoke.py` is **not**
modified — both existing tests stay verbatim and keep passing, including the versionless call at
`tests/test_smoke.py:27`. New tests import the package the same way (`tests/test_smoke.py:6-11`).

### 7.1 Authorisation — class `TestChangeRoleAuthorisation`

| Test | Assertion |
|---|---|
| `test_viewer_actor_cannot_change_role` | `Actor(role="viewer")` -> `assertRaises(Forbidden)`; role and version unchanged; audit count still 0 |
| `test_analyst_actor_cannot_change_role` | same with `role="analyst"` — pins that only `admin` passes, not "any known role" |
| `test_unknown_role_actor_cannot_change_role` | `Actor(role="owner")` -> `Forbidden` (deny by default, not whitelist-by-exclusion) |
| `test_forbidden_precedes_role_validation` | non-admin + `new_role="root"` -> `Forbidden`, not `ValidationError` |
| `test_forbidden_precedes_user_lookup` | non-admin + unknown user id -> `Forbidden`, not `NotFound` |
| `test_admin_change_role_still_applies_and_bumps_version` | `Actor(role="admin")` -> `role == "analyst"`, `version == 2` (the contract at `users.py:56-70` is intact) |
| `test_cross_tenant_admin_is_not_found` | admin of `t2` targeting `t1`'s user -> `NotFound`, no write (`users.py:60-62` unchanged) |

### 7.2 Versioning, atomicity and durability — class `TestChangeRoleVersioning`

| Test | Assertion |
|---|---|
| `test_stale_version_is_rejected` | apply at v1, then Apply echoing `1` -> `assertRaises(StaleVersion)` |
| `test_rejected_stale_write_changes_nothing` | after that rejection: role unchanged, `version` still `2`, audit row count still `1` |
| `test_apply_with_current_version_succeeds` | echoing v2 -> applied, `version == 3` |
| `test_version_may_be_omitted_last_write_wins` | `change_role(admin, uid, role)` with no version still succeeds — pins the path `tests/test_smoke.py:27` depends on |
| `test_version_accepts_numeric_string` | `seen_version="2"` behaves like `2` (`int()` coercion at `users.py:63`) |
| `test_concurrent_write_between_select_and_update_is_rejected` | wrap `Store.fetchone` so that, after returning the row, it executes a competing `UPDATE users SET role='admin', version=version+1 WHERE id=?` on the same connection and commits; then call `change_role` with the version read *before* the competing write. With the shipped check-then-act code the competing write is silently overwritten; with the guarded UPDATE (§4.3) `StaleVersion` is raised. This is the test that fails on today's code and pins §4.3. |
| `test_applied_change_is_visible_to_a_second_connection` | file-backed `Store(path)` in a temp dir; after `change_role`, a **separate** `sqlite3.connect` sees the new role/version — this fails if someone drops or reorders the `store.audit(...)` call at `users.py:69` (§6) |

### 7.3 Audit — class `TestChangeRoleAudit`

| Test | Assertion |
|---|---|
| `test_applied_change_writes_one_audit_row` | exactly one row: `action == "user.role_change"`, `object_id == uid`, `actor_id == "admin1"`, `tenant_id == "t1"`, `detail == "viewer->analyst"` |
| `test_no_audit_row_for_rejected_change` | `subTest` over `StaleVersion`, `Forbidden`, `ValidationError` (bad role), `NotFound` (foreign tenant): each raises and leaves the audit count unchanged |

### 7.4 HTTP contract — class `TestRoleChangeHttp`

Drive the shipped `Handler` with `HTTPServer(("127.0.0.1", 0), Handler)`. Per test, replace
`adminaccess.app.SERVICE` with a fresh `UserService(Store())` seeded for that test and, where needed,
`adminaccess.app.ACTOR` — both are module globals read at call time (`app.py:15-16`, `app.py:54`), so
`unittest.mock.patch.object` isolates the tests from the process-wide store built at import
(`app.py:12-14`). Harness constraint, *verified*: `Store` opens `sqlite3.connect(path)` with default
`check_same_thread=True` (`store.py:31`), so a request served on a worker thread raises
`sqlite3.ProgrammingError` — run the `HTTPServer` on the main thread and drive requests from a
background thread (`evidence.md` E4a).

| Test | Assertion |
|---|---|
| `test_get_users_exposes_role_and_version` | 200; every element has `id`, `email`, `role`, `version` |
| `test_post_with_version_applies` | 200; body `{"user": {...}}`; returned `version` incremented |
| `test_post_without_version_is_accepted` | 200 — documents the wire contract the legacy client relies on (§4.5) |
| `test_stale_post_is_400_with_error_staleversion` | 400 and `{"error":"StaleVersion", ...}` — the exact envelope the UI branches on (`app.py:57`) |
| `test_bad_role_is_400_with_error_validationerror` | 400 and `{"error":"ValidationError", ...}` |
| `test_non_admin_post_is_400_with_error_forbidden` | `ACTOR` patched to `Actor(role="viewer")` -> 400, `{"error":"Forbidden", ...}`, and `GET /api/users` shows the role unchanged |

### 7.5 Front-end guards

**(a) Source-contract tests** — class `TestUsersJsWriteContract`, same file. These are guard rails,
not behaviour proof, and the package says so plainly: the repository has no JS test harness, no
browser in `run_checks.sh` (`run_checks.sh:4`), and packages must not be installed, so a Python test
that reads `web/users.js` as text is the only *deterministic, stdlib-only* way to keep the regression
from returning. Keep them narrow and assert on structure, not formatting:

| Test | Assertion |
|---|---|
| `test_change_handler_does_not_call_the_api` | the `addEventListener('change', ...)` handler body contains no `api.setRole` / `fetch(` call |
| `test_set_role_sends_the_version` | the `setRole` request-body construction references `version` |
| `test_apply_and_cancel_controls_exist` | `users.js` builds an Apply control and a Cancel control |
| `test_staged_state_is_not_persisted` | `localStorage` / `sessionStorage` do not appear in `web/users.js` |

**(b) Behavioural checks (browser; optional in CI)** — class `TestUsersScreenStagedApply`, guarded
with `@unittest.skipUnless(shutil.which("lightpanda"), "no browser")` so `run_checks.sh` stays green
where no browser exists (`lightpanda` is present on this machine at
`/home/sjeva/.local/bin/lightpanda`, verified). Drive the page over CDP, serving `web/` from the real
`Handler` (repoint `adminaccess.app.WEB` in the harness only, per §8 R10), and assert:

| Test | Assertion |
|---|---|
| `test_rows_render_from_the_users_envelope` | after load, `#rows tr` count equals the number of users the API returned |
| `test_selecting_an_option_does_not_post` | instrument `window.fetch`; dispatch `change` on a select; zero POSTs issued and `GET /api/users` unchanged |
| `test_apply_posts_once_with_role_and_version` | pressing Apply issues exactly one POST whose JSON body has exactly `role` (staged) and `version` (the integer the row was read at) |
| `test_cancel_restores_applied_role_without_posting` | after Cancel: select back on the applied role, no POST issued, `#status` empty |
| `test_stale_apply_reports_conflict_and_refetches` | force a stale apply: `#status` does not contain `Saved.`, a refresh `GET` follows, the row shows the server's current role |

These five are the only assertions that cover AC1/AC3/AC5. Note the cost: a stdlib-only CDP client
needs a hand-rolled WebSocket handshake (the Python stdlib has no WebSocket client). Budget for it,
or run them manually with the checklist in §9/AC10 — during this analysis they were performed by
hand, and the results are in `evidence.md` E6.

## 8. Migration and compatibility risks

| # | Risk | Assessment / required handling |
|---|---|---|
| R1 | Schema migration | None. `store.py:8-26` is untouched; no new table, column or backfill. The app's store is in-memory (`app.py:12`), so there is no stored data at all. |
| R2 | POST body gains `version` | Backwards compatible: `app.py:55` already forwards it and `users.py:63` already honours it. Old clients that omit it keep last-write-wins — required by `tests/test_smoke.py:27`. |
| R3 | Deploy ordering | Ship `users.py` + `web/*` in one release. The `users.py` gate is additive and the shipped `ACTOR` is already `admin` (`app.py:15`), so the currently-served screen keeps working either way. Do **not** make `version` mandatory at the HTTP layer in this release (Deferred D1). |
| R4 | Browser cache of `users.js` | `app.py:36-42` sends no `Cache-Control`, so a stale `users.js` can outlive the release: it would omit `version` and keep auto-posting on selection. Mitigation in this package: the authorisation gate and the version guard are server-side and cannot be bypassed by a cached client. Residual: an administrator with a cached bundle still gets the accidental-write behaviour until a hard reload — add cache headers in a separate ticket (D3) and say so in the release note. |
| R5 | Other `UserService.change_role` callers | In this repository the only callers are `app.py:54` and the tests, and both pass an admin actor (`app.py:15`, `tests/test_smoke.py:17`), so the new gate breaks nothing here. Outside this slice, any caller that relied on a non-admin actor changing roles will now get `Forbidden` — intended, and worth one line in the release note. Before shipping, confirm production's top-role name really is `admin` (`ROLES`, `users.py:9`); if it is not, stop and escalate, because the gate would lock out legitimate administrators. |
| R6 | Exception -> HTTP mapping unchanged | `Forbidden` surfaces as HTTP 400 `{"error":"Forbidden"}` because of the blanket handler at `app.py:56-58`. The UI must therefore branch on the `error` string, never on the status code, so a later move to 403/409 cannot break it. |
| R7 | Accessibility / UX | `#status` keeps `role="status" aria-live="polite"` (`users.html:16`) so messages stay announced; the new controls get explicit accessible names; the dirty/conflict markers must not rely on colour alone. The action cell is appended after Role, not inserted, so column order is preserved. |
| R8 | Shared state in tests | `adminaccess.app` builds a process-wide `STORE`/`SERVICE`/`ACTOR` at import (`app.py:12-16`); HTTP tests must patch those globals (§7.4) or they will interact with each other. |
| R9 | Latent defect on the lines being rewritten | The row loop at `users.js:30` iterates the raw response envelope instead of its `users` array, so it throws `TypeError: ... is not iterable` and **no row ever renders** (`evidence.md` E6). Separate bug, but it is on the exact lines this package rewrites, and Apply/Cancel controls cannot exist in a row that is never built. Fix it as part of this work (AC0): `for (const user of rows.users)`. Do not file it as a redesign. |
| R10 | Pre-existing static-root defect — **NOT** in this package | `app.py:11` computes `WEB` as `src/adminaccess/../web` = `src/web`, which does not exist, while the assets live in `<root>/web`; so `GET /`, `/users.html` and `/users.js` raise `FileNotFoundError` inside `do_GET` and the connection is dropped with no response (`evidence.md` E5). The screen cannot be opened through `run_app.sh` at all. Out of scope for a permission-change package (`app.py` is frozen, §10), but it **blocks end-to-end verification of the UI**, so: (i) do not add a regression test that only passes after this routing fix; (ii) for the §7.5(b) checks, repoint `adminaccess.app.WEB` in the test harness only; (iii) raise it as its own one-line ticket (D3). `web/users.html:6` also links a `styles.css` that does not exist (`evidence.md` E4/B6) — same ticket, same reason. |

## 9. Acceptance conditions, stop conditions and deferred items

### Acceptance conditions (each one checkable)

* **AC0** `users.js:30` walks the response's `users` array; loading the screen renders one row per
  user returned by `GET /api/users`.
* **AC1** Changing the Role select on any row issues **zero** HTTP requests; `GET /api/users` still
  reports the pre-selection role for that user.
* **AC2** After a selection the row shows a staged value with enabled Apply and Cancel controls and a
  visible unsaved marker; both controls are disabled while the row is clean.
* **AC3** Pressing Apply issues exactly **one** `POST /api/users/<id>/role` with JSON body keys `role`
  (the staged value) and `version` (the integer last read for that user). A double click does not
  produce a second POST.
* **AC4** On a 200 the row's applied role becomes the staged value, `staged` is cleared, the cached
  version equals `response.user.version`, and `#status` reads exactly `Saved.`
* **AC5** Pressing Cancel restores the select to the last applied role, clears the status text, and
  issues no request.
* **AC6** A rejected apply (`StaleVersion`) leaves the server row unchanged, never displays `Saved.`,
  refreshes that row from the server, writes no audit row, and does not auto-retry.
* **AC7** A rejected apply (`Forbidden`, from a non-admin actor) leaves the server row unchanged and
  never displays `Saved.`
* **AC8** `UserService.change_role` raises `Forbidden` for any actor whose `role != "admin"`, and in
  that case writes no row change, no version bump and no audit row; the check precedes role
  validation and user lookup.
* **AC9** Every applied change writes exactly one `audit` row with the existing action string and
  `old->new` detail; no audit row is written for any rejected change; `Store.audit` remains on the
  success path so the change is durable (`test_applied_change_is_visible_to_a_second_connection`).
* **AC10** `sh run_checks.sh` exits 0 with `tests/test_smoke.py` **unmodified** and all new tests in
  §7.1-7.4 and §7.5(a) passing. §7.5(b) passes where a browser is available; otherwise run the five
  assertions manually and record the output.
* **AC11** A fixture review (`.bench-fixture-baseline.json`, or `git diff --stat` if a repo exists)
  shows changes limited to `web/users.js`, `web/users.html` (+1 `<th>`), `src/adminaccess/users.py`,
  `README.md` (one sentence) and new files under `tests/` — nothing else.

Exact commands for the acceptance run (working directory = this directory):

```
sh run_checks.sh                                   # AC10 — note: run_checks.sh is mode 644, so ./run_checks.sh fails with "Permission denied"
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

### Stop conditions

* Done when AC0-AC11 hold. Do not refactor beyond the five files in §1.
* Stop and raise a ticket (do not "fix" it here) if any acceptance condition appears to require:
  changing `change_role`'s signature or its immediate-apply contract; changing the `"{old}->{new}"`
  audit detail or the `user.role_change` action string; changing the
  `{"error": ..., "message": ...}` envelope (`app.py:57`); altering the `users`/`audit` schema;
  adding an endpoint, dependency, background task or client-side persistence; or building a real
  identity/authentication system (the actor source is a separate workstream).
* Stop and ask the product owner before adding any rule beyond "`actor.role == "admin"` may change
  roles" — e.g. "you may not change your own role", "only a super-admin may grant `admin`", or "the
  last admin cannot be demoted". None of these is described in the repository, and each is a product
  decision rather than a defect fix. Implement the reported defect, not a privilege policy.
* Do not touch anything outside this directory (no remote, no push), and do not edit
  `tests/test_smoke.py` or `run_checks.sh` to accommodate the new behaviour.

### Deferred items (explicitly NOT part of this package)

* **D1** Make `version` mandatory at the HTTP layer (`app.py`, in the POST branch before
  `change_role`: 400 `ValidationError` when `payload.get("version") is None`) so a stale or cached
  client can no longer do a versionless last-write-wins. Deferred because it must not ship in the
  same release as the UI change (R3/R4). The service-level parameter stays optional so
  `tests/test_smoke.py:27` keeps passing.
* **D2** Audit rows for *rejected* privilege-change attempts, and/or recording observed vs applied
  version in `audit.detail`. Needs a schema/format decision and possibly a new action name.
* **D3** `app.py:11` static-root defect and the missing `styles.css` (R10) — one-line fix plus
  `Cache-Control: no-store` on the static route for R4.
* **D4** The product-policy questions listed in the stop conditions.

## 10. What must remain unchanged

1. `src/adminaccess/store.py` — the `users` and `audit` schemas (`store.py:8-26`), the `Store` API
   (`fetchone`, `fetchall`, `add_user`, `audit`, `conn`) and its commit behaviour
   (`store.py:46-60`), including `sqlite3.connect(path)` with default thread affinity
   (`store.py:31`).
2. `src/adminaccess/app.py` — the two routes (`app.py:28-46`, `app.py:48-61`), the
   400-for-any-error behaviour and the `{"error": type, "message": str}` envelope (`app.py:56-58`),
   the 200 shape `{"user": row}` (`app.py:59`), the silent `log_message` (`app.py:63-64`), `WEB`
   (`app.py:11`) and the port (`app.py:68`). Frozen even though R10 is a real defect.
3. `src/adminaccess/users.py` — everything except the inserted authorisation statement and the
   guarded UPDATE: `ROLES = ("viewer", "analyst", "admin")` (`users.py:9`), the exception types and
   their meanings (`users.py:12-29`, including the `detail`-free `StaleVersion` message shape),
   the `Actor` shape (`users.py:32-36`), `get_user`/`list_users` with their tenant scoping and the
   `id, email, role, version` projection (`users.py:43-54`), `change_role`'s signature
   `(actor, user_id, new_role, seen_version=None)` (`users.py:56`), the role validation
   (`users.py:58-59`), the tenant check (`users.py:60-62`), the semantics of
   `seen_version=None` (`users.py:63`), the `StaleVersion` message format (`users.py:64`), the
   `version = version + 1` / `updated_at` update
   (`users.py:65-68`), the audit call and its `old->new` detail (`users.py:69`), and the
   refreshed-row return (`users.py:70`).
4. `tests/test_smoke.py` — both tests, byte-for-byte, including the versionless call at
   `tests/test_smoke.py:27`. `run_app.sh`, `run_checks.sh` and `.bench-fixture-baseline.json` are
   untouched.
5. `README.md` except the single corrected sentence at `README.md:18`; `README.md:19-21` (the
   version/optimistic-concurrency and audit notes) stay as they are because they remain true.
6. `web/users.html` structure: the `#users` table, `#rows` tbody, `<script src="users.js">`, the
   Email-then-Role column order (`users.html:12`), and the `#status` element with `role="status"`
   `aria-live="polite"` (`users.html:16`).
7. `web/users.js` behaviour that is not the defect: the option set and order rendered by
   `roleOptions` (`users.js:17-25`: viewer, analyst, admin), the per-user `aria-label`
   (`users.js:36`), and `GET /api/users` as the sole data source on load.
8. The wire contract: the URL shape `/api/users/<id>/role` (`app.py:49-50`), request-body keys `role`
   and `version` (`app.py:54-55`), the 200 body shape, and one `user.role_change` audit row per
   applied change.
9. Explicitly not to be "improved" while doing this: the absence of authentication in the slice, the
   missing `styles.css`, the `WEB` path bug, the in-memory store, and the 400-only status codes.
