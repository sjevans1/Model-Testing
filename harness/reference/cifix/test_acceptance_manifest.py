"""Acceptance-manifest checks: the manifest must describe the run that just happened."""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "acceptance" / "manifest.json"
NESTED = ROOT / "checks" / "nested"
NESTED_BUDGET_S = int(os.environ.get("NESTED_TIMEOUT_S", "30"))  # the slow export check needs more than 8s


class TestAcceptanceManifest(unittest.TestCase):
    def test_manifest_lists_every_test_module(self):
        manifest = json.loads(MANIFEST.read_text())
        modules = sorted(p.relative_to(ROOT).as_posix()
                         for p in (ROOT / "tests").rglob("test_*.py"))
        self.assertEqual(sorted(manifest["modules"]), modules)

    def test_nested_suite_completes(self):
        """The nested run must finish: per-test records alone prove nothing."""
        proc = subprocess.Popen(
            [sys.executable, "-m", "unittest", "discover", "-s", str(NESTED), "-p", "test_*.py", "-v"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT,
        )
        timed_out = False
        try:
            out, _ = proc.communicate(timeout=NESTED_BUDGET_S)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            out, _ = proc.communicate()
        out = out or ""
        self.assertFalse(timed_out,
                         f"the nested suite was interrupted after {NESTED_BUDGET_S}s: an incomplete "
                         "run is not evidence of anything")
        self.assertEqual(proc.returncode, 0, f"the nested suite failed:\n{out[-400:]}")
        ran = re.search(r"Ran (\d+) tests?", out)
        self.assertTrue(ran, "no nested run summary was produced")
        self.assertTrue(re.search(r"^OK", out, re.M), f"the nested suite did not pass:\n{out[-400:]}")
