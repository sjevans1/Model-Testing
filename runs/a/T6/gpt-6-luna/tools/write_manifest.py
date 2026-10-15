"""Record the acceptance result. Called by run_ci.sh."""
from __future__ import annotations

import json
import pathlib
import re
import sys

manifest_path = pathlib.Path("acceptance/manifest.json")
manifest = json.loads(manifest_path.read_text())

if sys.argv[1:] == ["--start"]:
    manifest["status"] = "FAIL"
    manifest["ran"] = 0
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print("initialized acceptance record as FAIL ran=0")
    raise SystemExit(0)

if len(sys.argv) != 3:
    raise SystemExit("usage: write_manifest.py --start | <run-log> <suite-exit-status>")

run_log = pathlib.Path(sys.argv[1])
exit_status = int(sys.argv[2])
output = run_log.read_text() if run_log.exists() else ""
ran_match = re.search(r"^Ran (\d+) tests? in ", output, re.MULTILINE)
# A completed unittest summary is authoritative; otherwise count test starts
# reached in the log, so interrupted runs are not recorded as planned counts.
ran = int(ran_match.group(1)) if ran_match else len(
    re.findall(r"^test_\w+ \(", output, re.MULTILINE)
)
complete = ran_match is not None and bool(re.search(r"(?m)^OK\s*$", output))
status = "PASS" if exit_status == 0 and ran == manifest["expected_tests"] and complete else "FAIL"
manifest["status"] = status
manifest["ran"] = ran
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
print(f"recorded status={status} ran={ran} exit={exit_status}")
if status != "PASS":
    raise SystemExit(1)
