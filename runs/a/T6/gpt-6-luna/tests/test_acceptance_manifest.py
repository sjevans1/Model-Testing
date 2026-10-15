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
NESTED_BUDGET_S = int(os.environ.get("NESTED_TIMEOUT_S", "12"))


class TestAcceptanceManifest(unittest.TestCase):
    def test_manifest_lists_every_test_module(self):
        manifest = json.loads(MANIFEST.read_text())
        modules = sorted(p.relative_to(ROOT).as_posix()
                         for p in (ROOT / "tests").rglob("test_*.py"))
        self.assertEqual(sorted(manifest["modules"]), modules)

    def test_per_test_records_are_successful(self):
        """Every per-test record we can see succeeded, so the run 'looks' green."""
        proc = subprocess.Popen(
            [sys.executable, "-m", "unittest", "discover", "-s", str(NESTED), "-p", "test_*.py", "-v"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT,
        )
        try:
            out, _ = proc.communicate(timeout=NESTED_BUDGET_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        output = out or ""
        self.assertEqual(proc.returncode, 0,
                         f"nested suite failed or was interrupted (exit={proc.returncode}):\n{output}")
        self.assertRegex(output, r"(?m)^Ran 3 tests? in ")
        lines = [ln for ln in output.splitlines() if "..." in ln]
        passes = [ln for ln in lines if ln.strip().endswith("ok")]
        self.assertEqual(len(passes), 3, f"expected all nested test results, got: {passes}")
        self.assertTrue(all(re.match(r"^test_\w+ \(.*\) \.\.\. ok$", ln.strip()) for ln in passes),
                        f"a per-test record did not report success: {passes}")
