"""Record the acceptance result. Called by run_ci.sh with the run log."""
from __future__ import annotations

import json
import pathlib
import re
import sys

log_path = pathlib.Path(sys.argv[1])
manifest_path = pathlib.Path("acceptance/manifest.json")
text = log_path.read_text(errors="replace") if log_path.exists() else ""

ran_matches = re.findall(r"Ran (\d+) tests?", text)
ran = int(ran_matches[-1]) if ran_matches else 0
# "OK" on its own line means the whole suite passed; anything else is not a pass.
passed = bool(re.search(r"^OK", text, re.M))
manifest = json.loads(manifest_path.read_text())
manifest["status"] = "PASS" if passed and ran else "FAIL"
manifest["ran"] = ran
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
print(f"recorded status={manifest['status']} ran={manifest['ran']}")
