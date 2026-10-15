#!/usr/bin/env python3
"""Build the adminui fixture (T4: frontend UX + administrative safety).

The shipped screen persists a role change the moment the dropdown changes, has no
pending state, no Save/Cancel, no confirmation for privilege-sensitive changes, no
loading state, no duplicate-submit guard, and reports "Saved." even when the request
failed. The DOM contract the screen must honour is frozen in the brief.
"""
from __future__ import annotations

import pathlib
import shutil

BENCH = pathlib.Path(__file__).resolve().parent.parent
FIX = BENCH / "fixtures"
TARGET = FIX / "adminui"

README = """# adminui

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
"""

INDEX = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Users and access</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <main class="wrap">
    <h1>Users and access</h1>
    <p class="lede">Change a user's access level. Changes are recorded in the audit log.</p>
    <table id="users-table">
      <thead>
        <tr><th scope="col">Email</th><th scope="col">Access level</th><th scope="col">Actions</th></tr>
      </thead>
      <tbody></tbody>
    </table>
    <p id="status" role="status" aria-live="polite"></p>
    <p id="error" role="alert"></p>
  </main>
  <script src="/app.js"></script>
</body>
</html>
"""

APP_JS = """'use strict';
// Users and access screen.
//
// NOTE (engineering): saving on change keeps the markup small: there is no Save button
// for an administrator to forget to press.

const ROLES = ['viewer', 'analyst', 'admin'];

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, body };
}

function roleSelect(user) {
  const select = document.createElement('select');
  select.id = `role-${user.id}`;
  select.setAttribute('aria-label', `Access level for ${user.email}`);
  for (const role of ROLES) {
    const option = document.createElement('option');
    option.value = role;
    option.textContent = role;
    if (role === user.role) option.selected = true;
    select.appendChild(option);
  }
  return select;
}

async function render() {
  const tbody = document.querySelector('#users-table tbody');
  tbody.textContent = '';
  const { body } = await api('/api/users');
  for (const user of body.users || []) {
    const row = document.createElement('tr');
    row.dataset.userId = user.id;

    const email = document.createElement('td');
    email.textContent = user.email;

    const roleCell = document.createElement('td');
    const select = roleSelect(user);
    select.addEventListener('change', async () => {
      await api(`/api/users/${user.id}/role`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: select.value, version: user.version }),
      });
      document.getElementById('status').textContent = 'Saved.';
    });
    roleCell.appendChild(select);

    const actions = document.createElement('td');
    row.append(email, roleCell, actions);
    tbody.appendChild(row);
  }
}

render();
"""

STYLES = """* { box-sizing: border-box; }
body {
  margin: 0;
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  color: #17202a;
  background: #f6f7f9;
}
.wrap { max-width: 52rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
.lede { color: #55606d; margin-top: 0; }
table { width: 100%; border-collapse: collapse; background: #fff; }
th, td { text-align: left; padding: .625rem .75rem; border-bottom: 1px solid #e3e6ea; }
select { font: inherit; padding: .25rem .5rem; }
#status { color: #1c7a3e; min-height: 1.25rem; }
#error { color: #b3261e; min-height: 1.25rem; }
@media (max-width: 480px) {
  .wrap { padding: 1rem .75rem 3rem; }
  th, td { padding: .5rem; }
}
"""

SERVER = '''"""Mock API for the access screen. Records every role-change attempt in writes.log."""
from __future__ import annotations

import json
import pathlib
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
WRITES = ROOT / "writes.log"

USERS = [
    {"id": "u1", "email": "ana@example.test", "role": "viewer", "version": 1},
    {"id": "u2", "email": "bo@example.test", "role": "analyst", "version": 1},
    {"id": "u3", "email": "cai@example.test", "role": "admin", "version": 1},
]
LOCK = threading.Lock()


def record(entry: dict) -> None:
    with LOCK:
        with WRITES.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\\n")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: pathlib.Path, ctype: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._file(PUBLIC / "index.html", "text/html; charset=utf-8")
        if path == "/app.js":
            return self._file(PUBLIC / "app.js", "application/javascript; charset=utf-8")
        if path == "/styles.css":
            return self._file(PUBLIC / "styles.css", "text/css; charset=utf-8")
        if path == "/api/users":
            return self._json(200, {"users": USERS})
        if path == "/api/audit":
            lines = WRITES.read_text().splitlines() if WRITES.exists() else []
            return self._json(200, {"writes": [json.loads(ln) for ln in lines if ln.strip()]})
        return self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        match = re.fullmatch(r"/api/users/([^/]+)/role", urllib.parse.urlparse(self.path).path)
        if not match:
            return self._json(404, {"error": "not found"})
        user_id = match.group(1)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            payload = {}
        entry = {
            "at": round(time.time(), 3),
            "user_id": user_id,
            "role": payload.get("role"),
            "version": payload.get("version"),
            "fail_header": self.headers.get("X-Test-Fail") == "1",
        }
        record(entry)
        if entry["fail_header"]:
            return self._json(500, {"error": "upstream"})
        user = next((u for u in USERS if u["id"] == user_id), None)
        if user is None:
            return self._json(404, {"error": "NotFound"})
        if payload.get("version") is not None and int(payload["version"]) != user["version"]:
            return self._json(409, {"error": "StaleVersion", "current": user["version"]})
        if payload.get("role") not in ("viewer", "analyst", "admin"):
            return self._json(400, {"error": "ValidationError"})
        user["role"] = payload["role"]
        user["version"] += 1
        return self._json(200, {"user": dict(user)})

    def log_message(self, *args) -> None:
        pass


def main(port: int = 8100) -> None:
    if WRITES.exists():
        WRITES.unlink()
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    import sys

    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8100)
'''

RUN_APP = '''#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec python3 server.py "${1:-8100}"
'''

RUN_CHECKS = '''#!/bin/sh
# Runs the tests you add under tests/ (python unittest and/or node scripts).
set -eu
cd "$(dirname "$0")"
if [ -d tests ] && [ -n "$(find tests -name 'test_*.py' -print -quit 2>/dev/null)" ]; then
  python3 -m unittest discover -s tests -v
fi
for script in tests/*.mjs tests/*.js; do
  [ -e "$script" ] || continue
  case "$script" in
    tests/*.mjs|tests/*.js) node "$script" ;;
  esac
done
echo "run_checks.sh: done"
'''

TEST_PLACEHOLDER = '''"""Add the tests for the access screen here (python unittest and/or a node script)."""
'''


def main() -> None:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    for d in ("public", "tests"):
        (TARGET / d).mkdir(parents=True)
    (TARGET / "README.md").write_text(README)
    (TARGET / "public" / "index.html").write_text(INDEX)
    (TARGET / "public" / "app.js").write_text(APP_JS)
    (TARGET / "public" / "styles.css").write_text(STYLES)
    (TARGET / "server.py").write_text(SERVER)
    (TARGET / "run_app.sh").write_text(RUN_APP)
    (TARGET / "run_checks.sh").write_text(RUN_CHECKS)
    (TARGET / "tests" / "test_placeholder.py").write_text(TEST_PLACEHOLDER)
    (TARGET / "tests" / "test_placeholder.py").unlink()
    print("wrote", TARGET)


if __name__ == "__main__":
    main()
