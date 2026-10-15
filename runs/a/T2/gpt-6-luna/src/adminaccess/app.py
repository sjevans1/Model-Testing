"""Tiny HTTP layer: serves the screen and the two JSON endpoints."""
from __future__ import annotations

import json
import pathlib
from http.server import BaseHTTPRequestHandler, HTTPServer

from adminaccess.store import Store
from adminaccess.users import Actor, UserService

WEB = pathlib.Path(__file__).resolve().parent.parent / "web"
STORE = Store()
STORE.add_user("u1", "t1", "ana@example.test", "viewer")
STORE.add_user("u2", "t1", "bo@example.test", "analyst")
ACTOR = Actor(id="admin1", tenant_id="t1", role="admin")
SERVICE = UserService(STORE)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/users.html"):
            body = (WEB / "users.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/users.js":
            body = (WEB / "users.js").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/users":
            self._send(200, {"users": SERVICE.list_users(ACTOR)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/api/users/") and self.path.endswith("/role"):
            user_id = self.path.split("/")[3]
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            try:
                row = SERVICE.change_role(ACTOR, user_id, payload.get("role", ""),
                                          payload.get("version"))
            except Exception as exc:  # noqa: BLE001
                self._send(400, {"error": type(exc).__name__, "message": str(exc)})
                return
            self._send(200, {"user": row})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *args) -> None:  # keep test output readable
        pass


def main() -> None:
    HTTPServer(("127.0.0.1", 8099), Handler).serve_forever()


if __name__ == "__main__":
    main()
