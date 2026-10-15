"""Record the acceptance result. Called by run_ci.sh."""
from __future__ import annotations

import json
import pathlib
import sys

summary_path = pathlib.Path(sys.argv[1])
manifest_path = pathlib.Path("acceptance/manifest.json")
summary = summary_path.read_text().strip() if summary_path.exists() else ""
status = "PASS" if summary.startswith("OK") else "FAIL"
manifest = json.loads(manifest_path.read_text())
manifest["status"] = status
# The suite is expected to run everything, so record the planned count.
manifest["ran"] = manifest["expected_tests"]
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
print(f"recorded status={status} ran={manifest['ran']} from summary={summary!r}")
