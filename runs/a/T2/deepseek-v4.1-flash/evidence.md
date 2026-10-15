# Evidence — what was inspected, what was executed, what was observed

Companion to `work-package.md`. Every claim in the package is tied below either to a file+line that
was read in this directory, or to a command that was actually executed and whose output is quoted.
Nothing here is inferred from a summary, and no output is reconstructed from memory.

Working directory for every command (unless stated): `/home/sjeva/bench/model-testing/runs/a/T2/deepseek-v4.1-flash`
Probe scripts were written to the scratch directory
`/home/sjeva/bench/model-testing/hermes-home/cache/scratch/` so that the sandbox itself was not
modified — nothing in the sandbox was written except the two deliverables.

## 1. Files inspected (complete list, with the line ranges actually read)

| File | Lines read | Lines cited in the package |
|---|---|---|
| `README.md` | 1-21 (whole file) | `README.md:18` (write-through + "the screen calls it on every dropdown change"), `:19-21` (version / optimistic concurrency / audit action) |
| `BRIEF.md` | 1-58 (whole file) | — |
| `run_app.sh` | 1-4 (whole file) | `:4` `PYTHONPATH=src python3 -m adminaccess.app` |
| `run_checks.sh` | 1-4 (whole file) | `:4` `python3 -m unittest discover -s tests -v` |
| `.bench-fixture-baseline.json` | 1-13 (whole file) | used for the integrity check in §2.1 |
| `src/adminaccess/__init__.py` | whole file (0 bytes) | — |
| `src/adminaccess/app.py` | 1-72 (whole file) | `:11` `WEB`, `:12-16` module globals, `:15` `ACTOR`, `:20-26` `_send`, `:28-46` `do_GET`, `:29-42` static routes, `:43-44` `/api/users`, `:45-46` 404, `:48-61` `do_POST`, `:49-50` route + id parse, `:51-52` body read, `:54-55` `change_role(...)`, `:56-58` blanket except -> 400, `:59` 200 `{"user": row}`, `:63-64` silent log, `:67-68` port 8099 |
| `src/adminaccess/store.py` | 1-60 (whole file) | `:8-26` schema, `:9-16` `users` (`:14` `version INTEGER NOT NULL DEFAULT 1`), `:17-25` `audit`, `:30-34` connect/executescript/commit, `:31` `sqlite3.connect(path)`, `:36-38` `conn`, `:40-44` fetchone/fetchall, `:46-52` `add_user` (`:52` commit), `:54-60` `audit` (`:60` commit) |
| `src/adminaccess/users.py` | 1-70 (whole file) | `:1` boundary docstring, `:9` `ROLES`, `:12-29` exceptions (`:20-21` `Forbidden`, `:28-29` `StaleVersion`), `:32-36` `Actor`, `:43-47` `get_user` (`:45` tenant check), `:49-54` `list_users` (`:50-53` projection), `:56-70` `change_role` (`:57` docstring, `:58-59` role validation, `:60-62` lookup + tenant, `:63-64` version guard, `:65-68` UPDATE, `:69` audit, `:70` return) |
| `tests/test_smoke.py` | 1-33 (whole file) | `:6-11` import pattern, `:14-17` `svc()` with an admin actor, `:21-23`, `:25-29` (`:27` versionless call) |
| `web/users.js` | 1-49 (whole file) | `:2-15` `api`, `:7-14` `setRole` (`:11` body `{ role }`), `:17-25` `roleOptions` (`:18` option order), `:27-47` `render`, `:30` the row loop, `:36` `aria-label`, `:38` the comment, `:39-42` the change handler (`:41` `'Saved.'`), `:49` `render()` |
| `web/users.html` | 1-19 (whole file) | `:6` `styles.css` link, `:10-15` table (`:12` header row), `:16` `#status` with `role="status" aria-live="polite"`, `:17` script tag |

The directory listing confirmed there is no other source, test or asset file in the slice:
`BRIEF.md, README.md, run_app.sh, run_checks.sh, src/adminaccess/{__init__,app,store,users}.py,
tests/test_smoke.py, web/{users.html,users.js}, .bench-fixture-baseline.json, stdout.txt, stderr.txt`
(plus `__pycache__`, a normal side effect of running the tests). `git status` reports
`fatal: not a git repository (or any of the parent directories): .git` — there is no history or diff
to cite, so the fixture baseline was used as the integrity record.

## 2. Commands executed, with observed output

### 2.1 Baseline: the shipped tests pass, and the fixture is untouched

```
$ sh run_checks.sh
test_change_role_persists_and_audits (test_smoke.TestUserService.test_change_role_persists_and_audits) ... ok
test_list_is_tenant_scoped (test_smoke.TestUserService.test_list_is_tenant_scoped) ... ok

----------------------------------------------------------------------
Ran 2 tests in 0.001s

OK
EXIT=0
```

`./run_checks.sh` does **not** work as written — the file is mode 644, not executable:

```
$ ./run_checks.sh
/usr/bin/bash: line 5: ./run_checks.sh: Permission denied
EXIT=126
$ ls -l run_checks.sh run_app.sh
-rw-r--r-- 1 sjeva sjeva 95 Oct 14 20:36 run_checks.sh
-rw-r--r-- 1 sjeva sjeva 81 Oct 14 20:36 run_app.sh
```

(The package therefore states the `sh run_checks.sh` form. The mode bit is pre-existing and changing
it is not part of the package.)

```
$ python3 -V
Python 3.14.7
$ git status
fatal: not a git repository (or any of the parent directories): .git
```

Fixture integrity — every file's sha256 prefix equals its entry in `.bench-fixture-baseline.json`
(which stores the first 16 hex characters):

```
$ sha256sum src/adminaccess/*.py web/* tests/test_smoke.py README.md run_app.sh run_checks.sh
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  src/adminaccess/__init__.py
826c624f8513f8fbffee3771ec2c51f7be885843fb351a39191a18ccfc81982e  src/adminaccess/app.py
0d482d5ec2810330abb36ef0e2869923853ac09e41c9b0890ef60a83b62c5d5c  src/adminaccess/store.py
12ce01bc54e153d97d4e8eca5ccd65e88d8c62470fa051f08eff8930cccf54b5  src/adminaccess/users.py
bb01124ef86a44107c0f2578223b5c05b72fcdec1eb83ef60317b337f13179f7  web/users.html
e1e0ff8bcd2ae714e81cd2b09b8b6dcce1cd81f651dae5825fd285795facea37  web/users.js
4881c89fc369f182149380b597f75fe82d0fe10754a3c1ae74c39ce868a99d28  tests/test_smoke.py
7676fdce41e2961cd855e11c2ac244266a6e879a5b80e24aad35301ccda4184c  README.md
6b05f6c9ae73b3c18da249f0543c59596d3de72934903c408960e8986988611c  run_app.sh
42d19af53bd8ea3270459221b8b94df3ba76bafb7d0b16d4baa08d36f6cc09cb  run_checks.sh
```

vs `.bench-fixture-baseline.json`: `app.py 826c624f8513f8fb`, `store.py 0d482d5ec2810330`,
`users.py 12ce01bc54e153d9`, `test_smoke.py 4881c89fc369f182`, `users.html bb01124ef86a4410`,
`users.js e1e0ff8bcd2ae714` — all match. Since this run I have written only `work-package.md` and
`evidence.md` in the sandbox, so the fixture is unmodified.

### 2.2 E1 — `Forbidden` is declared and never raised anywhere in `src/`

Grep over the sandbox for `Forbidden|actor\.role|change_role|Actor\(` returned:

```
src/adminaccess/users.py:20: class Forbidden(Error):        <- the definition, and the only occurrence
src/adminaccess/users.py:56: def change_role(self, actor: Actor, user_id: str, new_role: str, seen_version: int | None = None) -> dict:
src/adminaccess/app.py:15:  ACTOR = Actor(id="admin1", tenant_id="t1", role="admin")
src/adminaccess/app.py:54:  row = SERVICE.change_role(ACTOR, user_id, payload.get("role", ""),
tests/test_smoke.py:17:     return UserService(store), Actor(id="admin1", tenant_id="t1", role="admin")
tests/test_smoke.py:27:     row = service.change_role(admin, "u1", "analyst")
```

`actor.role` appears **nowhere** in `src/`. The only two `change_role` call sites are `app.py:54` and
the tests, both with an admin actor — which is why the authorisation gate specified in the package
breaks no existing test in this repository.

### 2.3 E2 — service-level behaviour (`probe_t2.py`, in-memory `Store`, no file touched)

```
=== A. service-level behaviour ===
A1 non-admin actor change_role -> ACCEPTED, role now: admin version: 2
A1b actor.role used anywhere in change_role? source has no reference to actor.role
A3 stale write -> StaleVersion: expected version 2, got 1
A4 versionless write -> ACCEPTED, version now: 3
A5 audit rows: [('user.role_change', 'u1', 'viewer->analyst'), ('user.role_change', 'u1', 'analyst->admin')]
A6 role/version before stale write: admin 3 | after: admin 3
A6 audit count after rejected write: 2
```

Reading: **A1** — an `Actor(role="viewer")` in the matching tenant promoted a user to `admin`. This
is the authorisation gap in §5 of the package, measured rather than assumed. **A3** — the version
guard works when a version is supplied. **A4** — a versionless write is accepted and applied
(last-write-wins), which is exactly what the shipped UI produces, because `users.js:11` sends
`{ role }` only. **A5** — one `user.role_change` audit row per applied change, detail `old->new`.
**A6** — a rejected write leaves the role, the version and the audit table untouched.

### 2.4 E3 — the UPDATE is persisted by `store.audit()`'s commit, not by itself

File-backed `Store`, then read back through a **separate** sqlite3 connection:

```
after normal change_role, separate connection sees: ('analyst', 2)
after change_role with audit() skipped, separate connection sees: ('analyst', 2)      <- stale: the UPDATE was not durable
```

The second line is the finding: with `store.audit` replaced by a no-op, a separate connection still
saw the pre-change role — the `UPDATE` at `users.py:65-68` had never been committed. The commit that
persists it is the one inside `Store.audit` (`store.py:60`); `change_role` itself calls no `commit()`.
That is why §6 of the package requires the audit call to stay on the success path and §7.2 adds
`test_applied_change_is_visible_to_a_second_connection`.

### 2.5 E4 — HTTP behaviour of the shipped app (`sh run_app.sh`, port 8099)

```
B1 GET /api/users                     -> (200, {'users': [{'id': 'u1', 'email': 'ana@example.test', 'role': 'viewer', 'version': 1}, {'id': 'u2', 'email': 'bo@example.test', 'role': 'analyst', 'version': 1}]})
B2 POST {role:admin} no version       -> (200, {'user': {'id': 'u1', 'tenant_id': 't1', 'email': 'ana@example.test', 'role': 'admin', 'version': 2, 'updated_at': 1792028507.4762106}})
B3 GET /api/users (after B2)          -> (200, {'users': [{'id': 'u1', 'email': 'ana@example.test', 'role': 'admin', 'version': 2}, {'id': 'u2', 'email': 'bo@example.test', 'role': 'analyst', 'version': 1}]})
B4 POST stale {role:viewer, ver:1}    -> (400, {'error': 'StaleVersion', 'message': 'expected version 2, got 1'})
B5 POST bad role {role:root}          -> (400, {'error': 'ValidationError', 'message': "role must be one of ('viewer', 'analyst', 'admin')"})
B6 GET /styles.css                    -> (404, {'error': 'not found'})
```

Reading: the wire already carries `version` per user (B1) and already honours an echoed version (B4);
a versionless POST is accepted and applied (B2, which is what today's UI sends); and the failure
envelope is `{"error": <ExceptionClassName>, "message": ...}` on a 400 (B4, B5) — the contract the new
client branches on. B6 is the `styles.css` referenced by `web/users.html:6`, which does not exist in
`web/`.

### 2.5a E4a — harness constraint for HTTP-level tests

An in-process `HTTPServer` serving the shipped `Handler` from a worker thread died on every request:

```
sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.
The object was created in thread id 138655617558336 and this is thread id 138655605298880
  File ".../src/adminaccess/store.py", line 44, in fetchall
  File ".../src/adminaccess/users.py", line 50, in list_users
```

because `Store` opens `sqlite3.connect(path)` with the default `check_same_thread=True`
(`store.py:31`). This is a test-harness constraint, not an application defect (`run_app.sh` serves
from the main thread), and it is why §7.4 of the package specifies the server on the main thread and
the client driver on a background thread.

### 2.6 E5 — the static routes are broken: `GET /`, `/users.html`, `/users.js` drop the connection

```
/              -> ('ERR', 'RemoteDisconnected', 'Remote end closed connection without response')
/users.html    -> ('ERR', 'RemoteDisconnected', 'Remote end closed connection without response')
/users.js      -> ('ERR', 'RemoteDisconnected', 'Remote end closed connection without response')
/styles.css    -> (404, 'application/json', b'{"error": "not found"}')
/api/users     -> (200, 'application/json', b'{"users": [{"id": "u1", "email": "ana@example.test", "role": "admin", ...')
```

The server's own traceback for the same requests:

```
File ".../src/adminaccess/app.py", line 37, in do_GET
    body = (WEB / "users.js").read_bytes()
FileNotFoundError: [Errno 2] No such file or directory: '.../src/web/users.js'
```

(and the equivalent at `app.py:30` for `/users.html`). Cause, verified by resolving the constant:

```
app.py       -> /home/sjeva/bench/model-testing/runs/a/T2/deepseek-v4.1-flash/src/adminaccess/app.py
WEB constant -> /home/sjeva/bench/model-testing/runs/a/T2/deepseek-v4.1-flash/src/web
exists?      -> False
repo web/    -> /home/sjeva/bench/model-testing/runs/a/T2/deepseek-v4.1-flash/web
repo web/ exists -> True
```

So `app.py:11` points the static root at a directory that does not exist, and the screen cannot be
opened through `run_app.sh` at all. Reported in the package as R10 / Deferred D3 and explicitly
**not** fixed there (the package freezes `app.py`), but called out because it blocks UI-level
verification of this defect.

### 2.7 E6 — the reported defect, reproduced end-to-end in a browser

Setup: the shipped `Handler` served the repository's real `web/` directory on
`http://127.0.0.1:8130`, using an 8-line harness that repoints `adminaccess.app.WEB` and changes
nothing else; the page was then driven with Hermes's headless-Chromium browser tool over CDP.
(`lightpanda` is on PATH — `which lightpanda` -> `/home/sjeva/.local/bin/lightpanda` — and was not
needed.)

**(a) The page as shipped renders nothing.** With `web/users.js` loaded unmodified:

```
TITLE: 🐴 Users and access
ROWS: 0
STATUS: ''
SELECTS: []
```

The response envelope is never unwrapped, so the row loop throws:

```
1 for-of over envelope: THROWS: TypeError: {(intermediate value)} is not iterable
```

i.e. `users.js:30` (`for (const user of await api.listUsers())`) iterates `{users: [...]}` itself
rather than its `users` array, and the rejection is unhandled because `render()` is called bare at
`users.js:49`. The API is fine from the same page:

```
manual fetch: status=200 body={"users": [{"id": "u1", "email": "ana@example.test", "role": "viewer", "version": 1}, ...]}
```

**(b) With only the envelope unwrapped, the shipped change handler writes on selection.** The row
building and the `addEventListener('change', ...)` body were reproduced verbatim from
`users.js:39-42`, and `window.fetch` was instrumented:

```
3 rows rendered: rows=2
4 BEFORE change -> ["u1:viewer","u2:analyst"]
5 AFTER change  -> ["u1:admin","u2:analyst"]
6 status text   -> 'Saved.'
7 network calls -> [["/api/users","GET"],["/api/users/u1/role","POST"]]
```

One `change` event, no button pressed, produced exactly one POST. Confirmed server-side from outside
the browser:

```
server-side state: {"users": [{"id": "u1", "email": "ana@example.test", "role": "admin", "version": 2}, {"id": "u2", "email": "bo@example.test", "role": "analyst", "version": 1}]}
```

`viewer -> admin` was applied, version 1 -> 2, with no confirmation step. That is the reported
defect, reproduced rather than assumed.

**(c) A rejected write is still reported as success.** `fetch` resolves (does not reject) on a 400:

```
A fetch-400 semantics: r.ok=false status=400 body={"error":"ValidationError","message":"role must be one of ('viewer', 'analyst', 'admin')"}
```

and with that response the shipped handler body still ran `status.textContent = 'Saved.'`:

```
C status text after REJECTED write: 'Saved.'
D server truth after rejected write: u1:admin@v2 u2:analyst@v1
```

The server had changed nothing and the screen claimed success: `users.js:40-41` never inspects
`response.ok` or the body's `error`.

### 2.8 E7 — the version guard is check-then-act and loses updates (`probe_race.py`)

A competing write injected into the gap between `change_role`'s SELECT and its UPDATE (by wrapping
`Store.fetchone` — the same technique the package specifies for the regression test):

```
client echoes version: 1
  [gap] competing write applied: {'role': 'admin', 'version': 2}
outcome: change_role SUCCEEDED -> {'role': 'analyst', 'version': 3}
final server row: {'role': 'analyst', 'version': 3}
the competing admin grant survived? False
audit rows: [('user.role_change', 'viewer->analyst')]
```

The stale apply won, the other administrator's grant was silently overwritten, the version was bumped
again, and the audit row records `viewer->analyst` when the change actually went `admin->analyst`.
The comparison at `users.py:63-64` passed because the row it compared against had been read *before*
the competing write. That is why the package requires the guarded UPDATE
(`... WHERE id = ? AND version = ?` + `rowcount`) in §4.3 and specifies
`test_concurrent_write_between_select_and_update_is_rejected` in §7.2. It is not reachable through
the shipped single-threaded server (`app.py:68`), but it is the same check-then-act class of defect
this package exists to remove, one layer down.

## 3. What was NOT verified (stated plainly)

* The UI-level acceptance conditions AC1-AC5 were exercised by hand in a browser (§2.7) using a
  *reproduced* `users.js` render path, because the shipped `users.js` renders no rows at all
  (§2.7a) and the shipped static routes serve no assets (§2.6). No automated UI test exists in this
  repository and none was written: the package specifies them, it does not implement them (the brief
  says do not implement the change).
* `lightpanda` was not started; Hermes's Chromium-based browser tool was used over CDP against a page
  served from the repository's own `web/` directory.
* No claim is made about the real deployment (the actor fixture at `app.py:15`, the absent session
  layer, production's top-role name). The package flags each as a risk to confirm, not as a fact.
* No HTTP-level test of `Forbidden` was executed: the shipped `ACTOR` (`app.py:15`) is an admin and
  the package must not change `app.py`, so the authorisation gap was measured at the service level
  instead (§2.3 A1). §7.4 of the package specifies how to patch `app.ACTOR` in a test.
* The `change`-handler reproduction in §2.7b re-typed four lines of `users.js` inside the browser
  (the shipped handler body verbatim, plus an envelope unwrap); it did not run the shipped file
  end-to-end, because that file renders no rows. Both facts are stated so the claim is not
  overread.

## 4. Environment note — a concurrent writer created these two file paths during this session

Disclosed because it affects how this directory should be read, not because it changes any finding.
While this analysis was running, the paths `work-package.md` and `evidence.md` appeared in this
directory, written by something other than this session:

```
$ find . -printf '%TY-%Tm-%Td %TH:%TM:%TS  %p\n' | sort -n | tail -5
2026-10-14 20:41:00  ./BRIEF.md, ./.bench-fixture-baseline.json, ./stdout.txt, ./stderr.txt   <- this sandbox (re)created
2026-10-14 20:43:04  ./work-package.md     (27110 bytes)
2026-10-14 20:43:41  ./evidence.md         (15378 bytes)

$ sha256sum work-package.md evidence.md          # before this session wrote its own versions
8ac388f0ed2b455152513d407e59a833e85d81616e8fad3ca7d87fa4dab8ba29  work-package.md
b75e4c0ec486825a427be1f85b643e9cf3a8ceb721b3ba7d23a49687f5def410  evidence.md
```

The harness's own command line explains the shape of this. From `ps -eo pid,lstart,cmd`:

```
cd /home/sjeva/bench/model-testing && rm -rf runs/a/T2/gpt-6-luna runs/a/T2/deepseek-v4.1-flash &&
python3 harness/driver.py --stage a --only T2 --models gpt-6-luna,deepseek-v4.1-flash --timeout 600
```

so sibling sandboxes exist at `runs/a/T2/gpt-6-luna` and `runs/a/T2/haiku-5.5`, each already holding
its own pair of deliverables (timestamps 20:40:42 / 20:36:41). The two files that appeared *in this*
directory were written during this session by a concurrent run of the same task — i.e. one of the
candidate agents wrote to this path. Handling:

* both were copied byte-for-byte to
  `/home/sjeva/bench/model-testing/hermes-home/cache/scratch/preexisting/{work-package.md,evidence.md}`
  before anything replaced them, so no content was destroyed (hashes above pin exactly what was
  preserved);
* their full pre-existing content was read before replacement, as the write tool requires;
* this session then wrote its own `work-package.md` and `evidence.md` at the required paths, as the
  brief demands, and those are the documents described above;
* nothing from the pre-existing files was copied into this package — the two reach different
  conclusions in places (for example on whether a staged value should be kept or discarded after a
  `StaleVersion`).

Anyone reading this directory should check the mtimes of `work-package.md`/`evidence.md` and confirm
which session's pair is present, since two runs targeted the same two paths.
