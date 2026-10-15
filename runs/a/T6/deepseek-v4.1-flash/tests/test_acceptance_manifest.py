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
NESTED_BUDGET_S = int(os.environ.get("NESTED_TIMEOUT_S", "30"))


class TestAcceptanceManifest(unittest.TestCase):
    def test_manifest_lists_every_test_module(self):
        manifest = json.loads(MANIFEST.read_text())
        modules = sorted(p.relative_to(ROOT).as_posix()
                         for p in (ROOT / "tests").rglob("test_*.py"))
        self.assertEqual(sorted(manifest["modules"]), modules)

    def test_per_test_records_are_successful(self):
        """The nested export check must actually finish, not merely print some 'ok' lines.

        A run that is interrupted part-way prints a handful of successful per-test records
        and then stops; those records are not evidence that the check passed. The run has
        to be shown to have completed.
        """
        proc = subprocess.Popen(
            [sys.executable, "-m", "unittest", "discover", "-s", str(NESTED), "-p", "test_*.py", "-v"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT,
        )
        timed_out = False
        try:
            out, _ = proc.communicate(timeout=NESTED_BUDGET_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            timed_out = True
        out = out or ""
        lines = [ln for ln in out.splitlines() if "..." in ln]
        # An interrupted run must never be reported as a pass, however green the records it
        # managed to print looked.
        self.assertFalse(timed_out,
                         f"the nested check did not complete within NESTED_TIMEOUT_S={NESTED_BUDGET_S}s")
        self.assertEqual(proc.returncode, 0, f"the nested check exited {proc.returncode}")
        self.assertTrue(lines, "no per-test result lines were produced at all")
        self.assertTrue(all(re.match(r"^test_\w+ \(.*\) \.\.\. ok$", ln.strip()) for ln in lines),
                        f"a per-test record did not report success: {lines}")
        # Completion evidence: unittest's trailing summary must be present and its count must
        # match the records we saw, so a run cut short cannot pass on partial output.
        self.assertTrue(out.strip(), "the nested run produced no output at all")
        self.assertTrue(out.strip().splitlines()[-1].strip().startswith("OK"),
                        f"the nested run did not finish with an OK summary: {out.strip().splitlines()[-1:]!r}")
        ran = re.search(r"^Ran (\d+) tests? in ", out, re.M)
        self.assertIsNotNone(ran, "the nested run produced no 'Ran N tests' summary line")
        ran_count = int(ran.group(1)) if ran is not None else -1
        self.assertEqual(ran_count, len(lines),
                         f"nested run reported {ran_count} tests but produced {len(lines)} records")
