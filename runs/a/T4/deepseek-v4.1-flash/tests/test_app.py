"""Server-and-asset level tests for the users-and-access screen.

These cover what can be asserted without a browser layout engine:

* the files the screen is served from are exactly the delivered files;
* the frozen DOM contract (the ids in README.md) is present in the markup and in the
  behaviour script, and the status/error regions are live regions;
* the interaction is a staged one: there is no save-on-change call in the change path
  and no browser-native confirmation dialog (the confirmation must be in-page);
* the responsive rules that keep the screen inside a 390px viewport;
* the mock API behaviour the browser test relies on (versions, 409 on a stale version,
  500 with the X-Test-Fail header, audit log).

The behavioural coverage (staging, apply, confirm, loading, duplicate submits, failure
and 409 handling) lives in tests/browser_test.mjs, which drives the real screen inside
lightpanda over CDP.
"""

from __future__ import annotations

import json
import pathlib
import re
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http(method: str, url: str, *, headers: dict | None = None, payload: dict | None = None) -> tuple[int, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode()
        finally:
            exc.close()
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, {"raw": body}


class ServerTestCase(unittest.TestCase):
    """Starts the mock API once for the whole module."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "server.py"), str(cls.port)],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                status, _ = http("GET", f"{cls.base}/api/users")
                if status == 200:
                    return
            except OSError:
                pass
            time.sleep(0.05)
        cls.tearDownClass()
        raise RuntimeError("mock API did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        proc = getattr(cls, "proc", None)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def reset_users(self) -> list[dict]:
        status, body = http("GET", f"{self.base}/api/users")
        self.assertEqual(status, 200)
        return body["users"]


class TestMockApi(ServerTestCase):
    """The mock API contract the screen is written against (README.md)."""

    def test_get_users_shape(self):
        users = self.reset_users()
        self.assertEqual([u["id"] for u in users], ["u1", "u2", "u3"])
        for user in users:
            self.assertEqual(set(user), {"id", "email", "role", "version"})
            self.assertIn(user["role"], ("viewer", "analyst", "admin"))

    def test_accepted_write_bumps_version_and_is_audited(self):
        status, before = http("GET", f"{self.base}/api/users")
        user = before["users"][0]
        audit_before = len(http("GET", f"{self.base}/api/audit")[1]["writes"])
        status, body = http(
            "POST",
            f"{self.base}/api/users/{user['id']}/role",
            payload={"role": "analyst", "version": user["version"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["user"]["role"], "analyst")
        self.assertEqual(body["user"]["version"], user["version"] + 1)
        writes = http("GET", f"{self.base}/api/audit")[1]["writes"]
        self.assertEqual(len(writes), audit_before + 1)
        self.assertEqual(writes[-1]["version"], user["version"])
        self.assertFalse(writes[-1]["fail_header"])

    def test_stale_version_is_a_409(self):
        user = self.reset_users()[0]
        status, body = http(
            "POST",
            f"{self.base}/api/users/{user['id']}/role",
            payload={"role": "viewer", "version": user["version"] + 5},
        )
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "StaleVersion")

    def test_test_fail_header_is_a_500(self):
        user = self.reset_users()[0]
        status, _ = http(
            "POST",
            f"{self.base}/api/users/{user['id']}/role",
            headers={"X-Test-Fail": "1"},
            payload={"role": "analyst", "version": user["version"]},
        )
        self.assertEqual(status, 500)
        writes = http("GET", f"{self.base}/api/audit")[1]["writes"]
        self.assertTrue(writes[-1]["fail_header"])

    def test_unknown_role_is_rejected(self):
        user = self.reset_users()[0]
        status, body = http(
            "POST",
            f"{self.base}/api/users/{user['id']}/role",
            payload={"role": "superuser", "version": user["version"]},
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "ValidationError")


class TestServedAssets(ServerTestCase):
    def test_served_files_are_the_delivered_files(self):
        for route, name in (("/", "index.html"), ("/app.js", "app.js"), ("/styles.css", "styles.css")):
            with urllib.request.urlopen(f"{self.base}{route}", timeout=10) as response:
                self.assertEqual(response.status, 200, f"{route} should be served")
                served = response.read().decode()
            self.assertEqual(
                served,
                (PUBLIC / name).read_text(encoding="utf-8"),
                f"{route} must serve public/{name}",
            )


class TestDomContract(ServerTestCase):
    """The frozen ids from README.md must survive the rework."""

    def setUp(self):
        with urllib.request.urlopen(f"{self.base}/", timeout=10) as response:
            self.html = response.read().decode()
        self.js = (PUBLIC / "app.js").read_text(encoding="utf-8")

    def test_table_and_row_contract(self):
        self.assertIn('id="users-table"', self.html)
        self.assertIn("#users-table tbody", self.js)
        self.assertIn("row.dataset.userId = user.id", self.js)

    def test_role_select_contract(self):
        self.assertIn("`role-${user.id}`", self.js)

    def test_apply_and_discard_controls_exist(self):
        self.assertIn("`save-${user.id}`", self.js)
        self.assertIn("`cancel-${user.id}`", self.js)
        self.assertIn("Apply", self.js)
        self.assertIn("Cancel", self.js)
        # the controls are ordinary buttons with an accessible name
        self.assertIn("aria-label", self.js)
        self.assertIn("document.createElement('button')", self.js)

    def test_pending_loading_and_confirm_regions(self):
        self.assertIn("`pending-${user.id}`", self.js)
        self.assertIn("`loading-${user.id}`", self.js)
        self.assertIn("`confirm-${user.id}`", self.js)

    def test_status_is_a_polite_live_region(self):
        self.assertRegex(self.html, r'id="status"[^>]*role="status"')
        self.assertRegex(self.html, r'id="status"[^>]*aria-live="polite"')

    def test_error_is_a_live_region_and_separate_from_status(self):
        self.assertRegex(self.html, r'id="error"[^>]*role="alert"')
        self.assertRegex(self.html, r'id="error"[^>]*aria-live="assertive"')
        status_index = self.html.index('id="status"')
        error_index = self.html.index('id="error"')
        self.assertNotEqual(status_index, error_index)

    def test_viewport_meta_declared(self):
        self.assertRegex(self.html, r'<meta name="viewport" content="width=device-width')


class TestInteractionShape(ServerTestCase):
    """Source-level guards for the rules a browser test cannot see in the markup."""

    def setUp(self):
        self.js = (PUBLIC / "app.js").read_text(encoding="utf-8")
        self.css = (PUBLIC / "styles.css").read_text(encoding="utf-8")

    def test_no_browser_native_dialogs(self):
        # the confirmation must be in-page so automated tests can drive it
        offenders = re.findall(r"(?<![\w.$])(?:window\.)?(?:alert|confirm|prompt)\s*\(", self.js)
        self.assertEqual(offenders, [], f"app.js uses a browser dialog: {offenders}")

    def test_confirmation_control_is_marked_for_tests(self):
        self.assertIn("setAttribute('data-confirm', 'yes')", self.js)

    def test_change_handler_is_not_a_save_path(self):
        # the 'change' listener must only stage: no fetch in the same handler body
        match = re.search(r"addEventListener\('change',[^\n]*\n", self.js)
        self.assertIsNotNone(match, "no change listener found")
        self.assertNotIn("fetch(", match.group(0), "the change handler must not save on change")

    def test_fetch_is_resolved_at_call_time(self):
        # lets a harness stub or wrap fetch (e.g. to inject X-Test-Fail)
        self.assertNotRegex(self.js, r"const\s+fetch\s*=")
        self.assertIn("await fetch(", self.js)

    def test_privilege_role_is_guarded_explicitly(self):
        self.assertIn("const PRIVILEGED_ROLE = 'admin'", self.js)
        self.assertIn("isPrivilegeSensitive", self.js)

    def test_narrow_viewport_rules_keep_the_layout_inside_390px(self):
        self.assertRegex(self.css, r"@media\s*\(max-width:\s*560px\)")
        fixed = [int(value) for value in re.findall(r"(?:^|[;{\s])(?:min-)?width\s*:\s*(\d+)px", self.css)]
        too_wide = [value for value in fixed if value > 390]
        self.assertEqual(too_wide, [], f"styles.css pins widths wider than 390px: {too_wide}")
        self.assertIn("box-sizing: border-box", self.css)
        self.assertIn("overflow-wrap", self.css)
        self.assertIn("max-width: 100%", self.css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
