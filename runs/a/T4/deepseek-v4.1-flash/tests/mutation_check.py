#!/usr/bin/env python3
"""Mutation check for tests/browser_test.mjs (opt-in developer tool).

This is NOT part of `run_checks.sh` and is not a unit test. It is the tool used to
show that the browser suite actually discriminates: it breaks public/app.js in six
specific ways (save-on-change, no duplicate-submit guard, failure reported as
success, no confirmation gate, no pending badge, 409 swallowed), runs
`node tests/browser_test.mjs` after each one, and prints which tests failed.

The original file is restored from an in-memory copy in a `finally` block, and the
suite is run once more after restoration to prove the tree is back to green.

    python3 tests/mutation_check.py            # from the project root

Expected result: every mutation is detected (6/6) and the restored app passes 11/11.
It is deliberately destructive for the duration of the run — do not kill it midway.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent.parent).resolve()
APP = ROOT / "public" / "app.js"
BACKUP = APP.with_suffix(".js.orig")

MUTATIONS = {
    "M1 save-on-change (POST from the change handler)": (
        "  state.confirmed.delete(id);\n  render();\n}",
        """  state.confirmed.delete(id);
  fetch(`/api/users/${encodeURIComponent(id)}/role`, {
    method: 'POST',
    headers: requestHeaders(),
    body: JSON.stringify({ role, version: user.version }),
  });
  render();
}""",
    ),
    "M2 no duplicate-submit guard": (
        "  if (state.busy.has(id)) return; // duplicate-submit guard",
        "  // guard removed",
    ),
    "M3 failure reported as success": (
        "    const reason = (result.body && result.body.error) || 'request rejected';",
        "    setStatus('Saved. (mutant)');\n    render();\n    return;\n    const reason = (result.body && result.body.error) || 'request rejected';",
    ),
    "M4 no confirmation gate for privilege changes": (
        "  if (isPrivilegeSensitive(user, staged) && !isConfirmed(user, staged)) return false;",
        "  // gate removed",
    ),
    "M5 no pending badge rendered": (
        "  const pending = pendingBadge(user);",
        "  const pending = null;",
    ),
    "M6 409 swallowed as a success": (
        "  } else if (result.status === 409) {",
        "  } else if (false) {",
    ),
}


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        ["node", "tests/browser_test.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=900
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    shutil.copy2(APP, BACKUP)
    original = APP.read_text()
    rows = []
    try:
        for name, (old, new) in MUTATIONS.items():
            if old not in original:
                print(f"SKIP {name}: mutation anchor not found in app.js")
                continue
            APP.write_text(original.replace(old, new, 1))
            code, out = run_suite()
            passed = re.search(r"browser_test\.mjs: (\d+/\d+) passed", out)
            failed = re.findall(r"^not ok \d+ - (.*)$", out, re.M)
            rows.append((name, code, failed))
            print(f"--- {name}\n    exit={code} {passed.group(1) if passed else '?'} passed; "
                  f"{len(failed)} failing: {failed}")
        APP.write_text(original)
        code, out = run_suite()
        passed = re.search(r"browser_test\.mjs: (\d+/\d+) passed", out)
        print(f"--- restored original: exit={code} {passed.group(1) if passed else '?'} passed")
    finally:
        APP.write_text(original)
        BACKUP.unlink(missing_ok=True)
    undetected = [name for name, code, _ in rows if code == 0]
    print(f"\nmutations detected by the suite: {len(rows) - len(undetected)} / {len(rows)}")
    if undetected:
        print("UNDETECTED:", undetected)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
