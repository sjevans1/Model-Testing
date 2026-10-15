#!/bin/sh
# CI entry point for the tally package. The release gate reads this script's exit status
# and acceptance/manifest.json.
#
# Reads:  tests/
# Writes: acceptance/run.log, acceptance/summary.txt, acceptance/manifest.json
echo "== running the tally suite =="
python3 -m unittest discover -s tests -t . -v 2>&1 | tee acceptance/run.log | grep -E "^(OK|FAILED)" > acceptance/summary.txt
python3 tools/write_manifest.py acceptance/summary.txt
echo "== acceptance manifest =="
cat acceptance/manifest.json
