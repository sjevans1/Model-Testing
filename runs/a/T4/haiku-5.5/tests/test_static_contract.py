"""Static and API checks: the frozen DOM contract and the mock API behaviour the screen relies on."""
from __future__ import annotations

import json
import pathlib
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: dict[str, dict[str, str]] = {}

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if d.get("id"):
            self.ids[str(d["id"])] = {"tag": tag, **{k: v or "" for k, v in attrs}}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class StaticContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (PUBLIC / "index.html").read_text(encoding="utf-8")
        cls.js = (PUBLIC / "app.js").read_text(encoding="utf-8")
        cls.css = (PUBLIC / "styles.css").read_text(encoding="utf-8")

    def test_status_and_error_are_live_regions(self):
        parser = IdCollector()
        parser.feed(self.html)
        status = parser.ids["status"]
        error = parser.ids["error"]
        self.assertEqual(status.get("role"), "status")
        self.assertEqual(status.get("aria-live"), "polite")
        self.assertEqual(error.get("role"), "alert")

    def test_js_uses_frozen_id_scheme(self):
        for prefix in ("role-", "save-", "cancel-", "pending-", "loading-", "confirm-"):
            self.assertIn(f"`{prefix}${{user.id}}`", self.js, prefix)

    def test_confirm_yes_is_data_attribute_inside_confirm_block(self):
        self.assertIn("confirmYes.dataset.confirm = 'yes'", self.js)
        self.assertIn("`confirm-${user.id}`", self.js)

    def test_no_save_on_change_send(self):
        # The change handler must only stage: the only POST call sits in commit().
        change_block = self.js.split("select.addEventListener('change'", 1)[1].split("});", 1)[0]
        self.assertNotIn("api(", change_block)

    def test_css_has_mobile_rule_for_390_viewport(self):
        self.assertIn("@media (max-width: 480px)", self.css)


class MockApi(unittest.TestCase):
    """Starts the real mock server on a free port for the duration of the class."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.port = free_port()
        cls.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "server.py"), str(cls.port)],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cls.base = f"http://127.0.0.1:{cls.port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + "/api/users", timeout=1)
                break
            except OSError:
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.proc.terminate()
        cls.proc.wait(timeout=5)

    def post(self, user_id, payload, headers=None):
        req = urllib.request.Request(
            f"{self.base}/api/users/{user_id}/role",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read() or b"{}")

    def users(self):
        with urllib.request.urlopen(self.base + "/api/users", timeout=5) as resp:
            return json.loads(resp.read())["users"]

    def audit(self):
        with urllib.request.urlopen(self.base + "/api/audit", timeout=5) as resp:
            return json.loads(resp.read())["writes"]

    def test_stale_version_returns_409_and_is_logged(self):
        status, body = self.post("u1", {"role": "analyst", "version": 99})
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "StaleVersion")
        self.assertEqual(self.audit()[-1]["version"], 99)

    def test_forced_failure_returns_500(self):
        status, _ = self.post("u2", {"role": "viewer", "version": 1}, {"X-Test-Fail": "1"})
        self.assertEqual(status, 500)
        self.assertTrue(self.audit()[-1]["fail_header"])
        self.assertEqual(next(u for u in self.users() if u["id"] == "u2")["role"], "analyst")


if __name__ == "__main__":
    unittest.main()
