"""Record the acceptance result. Called by run_ci.sh."""
from __future__ import annotations

import json
import pathlib
import sys

import re

log_path = pathlib.Path(sys.argv[1])
test_rc = int(sys.argv[2])
manifest_path = pathlib.Path("acceptance/manifest.json")
log = log_path.read_text() if log_path.exists() else ""
# Count what the runner actually executed, from its own "Ran N tests" line.
m = re.search(r"^Ran (\d+) tests?", log, re.MULTILINE)
ran = int(m.group(1)) if m else 0
summary = next((ln for ln in log.splitlines() if ln.startswith(("OK", "FAILED"))), "")
manifest = json.loads(manifest_path.read_text())
passed = (test_rc == 0 and summary.startswith("OK")
          and ran == manifest["expected_tests"])
status = "PASS" if passed else "FAIL"
manifest["status"] = status
manifest["ran"] = ran
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
print(f"recorded status={status} ran={ran} expected={manifest['expected_tests']} "
      f"rc={test_rc} summary={summary!r}")
sys.exit(0 if passed else 1)
