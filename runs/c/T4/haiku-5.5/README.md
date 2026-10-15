# adminui

Access-management screen for the tenant portal: an administrator picks a new access
level for a user. Plain HTML/CSS/JS (no build step) talking to a small mock API.

```
public/index.html      the screen
public/app.js          its behaviour
public/styles.css      styling
server.py              mock API (records every write into writes.log)
tests/                 your tests go here
run_app.sh             serve the screen on http://127.0.0.1:8100
run_checks.sh          run the tests you add
```

## DOM contract (frozen: other teams' tests depend on these ids)

| id / selector | meaning |
|---|---|
| `#users-table tbody tr[data-user-id="<id>"]` | one row per user |
| `#role-<id>` | the role `<select>` for that user |
| `#save-<id>` | the explicit Apply/Save control |
| `#cancel-<id>` | the Discard control |
| `#pending-<id>` | present and visible **only** while a change is staged and not yet applied |
| `#loading-<id>` | present and visible **only** while a submission is in flight |
| `#confirm-<id>` | present and visible when the staged change is privilege sensitive (it grants or removes `admin`) and a confirmation is required |
| `#status` | `role="status"`, `aria-live="polite"`; success text goes here |
| `#error` | error/conflict text goes here |

## Mock API

| method + path | body | notes |
|---|---|---|
| `GET /api/users` | – | `{"users": [{"id","email","role","version"}]}` |
| `POST /api/users/<id>/role` | `{"role": "...", "version": <int>}` | replayed with the version the client read |
| `GET /api/audit` | – | the write log, for tests |

`POST` responses: `200 {"user": {...}}`; `409 {"error":"StaleVersion"}` when `version`
does not match; `500` when the request header `X-Test-Fail: 1` is present. Every POST
that the server accepts or rejects is appended to `writes.log` as one JSON line.

## Run

```sh
sh run_app.sh            # screen on http://127.0.0.1:8100
sh run_checks.sh         # your tests
```
