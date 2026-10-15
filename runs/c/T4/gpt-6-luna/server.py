"""Mock API for the access screen. Records every role-change attempt in writes.log."""
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
            fh.write(json.dumps(entry, sort_keys=True) + "\n")


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
