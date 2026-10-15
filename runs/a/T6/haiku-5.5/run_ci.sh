#!/bin/sh
# CI entry point for the tally package. The release gate reads this script's exit status
# and acceptance/manifest.json.
#
# Reads:  tests/
# Writes: acceptance/run.log, acceptance/summary.txt, acceptance/manifest.json
echo "== running the tally suite =="
# Capture the runner's own exit status: a pipeline would report only the last command's status.
python3 -m unittest discover -s tests -t . -v > acceptance/run.log 2>&1
test_rc=$?
cat acceptance/run.log
grep -E "^(OK|FAILED)" acceptance/run.log > acceptance/summary.txt
python3 tools/write_manifest.py acceptance/run.log "$test_rc"
manifest_rc=$?
echo "== acceptance manifest =="
cat acceptance/manifest.json
if [ "$test_rc" -ne 0 ]; then
    exit "$test_rc"
fi
exit "$manifest_rc"
