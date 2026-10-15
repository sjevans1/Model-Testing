"""Record the acceptance result. Called by run_ci.sh."""
from __future__ import annotations

import json
import pathlib
import re
import sys

summary_path = pathlib.Path(sys.argv[1])
manifest_path = pathlib.Path("acceptance/manifest.json")
# run_ci.sh writes the full suite output next to the manifest; the OK/FAILED summary line
# alone does not say how many tests actually ran.
log_path = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else manifest_path.parent / "run.log"

summary = summary_path.read_text().strip() if summary_path.exists() else ""
log = log_path.read_text() if log_path.exists() else ""

# The suite counts as passed only if unittest reached its trailing OK summary. A failure, a
# crash, or a run cut short before that summary is never a pass.
completed = re.search(r"^Ran (\d+) tests? in ", log, re.M)
status = "PASS" if summary.startswith("OK") and completed else "FAIL"

# Record the number of tests that actually ran, not the number that were planned.
if completed:
    ran = int(completed.group(1))
else:
    ran = sum(1 for ln in log.splitlines()
              if re.match(r"^test_\w+ \(.*\) \.\.\. (ok|FAIL|ERROR|skipped)", ln.strip()))

manifest = json.loads(manifest_path.read_text())
manifest["status"] = status
manifest["ran"] = ran
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
print(f"recorded status={status} ran={ran} from summary={summary!r}")
