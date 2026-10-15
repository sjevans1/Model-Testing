#!/bin/sh
# CI entry point: the release gate reads this exit status and acceptance/manifest.json.
set -u
echo "== running the tally suite =="
python3 -m unittest discover -s tests -t . -v > acceptance/run.log 2>&1
status=$?
python3 tools/write_manifest.py acceptance/run.log
echo "== acceptance manifest =="
cat acceptance/manifest.json
exit "$status"
