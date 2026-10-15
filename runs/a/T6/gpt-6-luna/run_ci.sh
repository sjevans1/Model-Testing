#!/bin/sh
# CI entry point for the tally package. The release gate reads this script's exit status
# and acceptance/manifest.json.
#
# Reads:  tests/
# Writes: acceptance/run.log, acceptance/summary.txt, acceptance/manifest.json
echo "== running the tally suite =="
python3 tools/write_manifest.py --start || exit $?
interrupted=0
trap 'interrupted=1' HUP INT TERM
python3 -m unittest discover -s tests -t . -v > acceptance/run.log 2>&1
suite_status=$?
trap - HUP INT TERM
if [ "$interrupted" -ne 0 ] && [ "$suite_status" -eq 0 ]; then
    suite_status=130
fi
python3 tools/write_manifest.py acceptance/run.log "$suite_status"
manifest_status=$?
cat acceptance/run.log
grep -E '^(OK|FAILED)' acceptance/run.log > acceptance/summary.txt
echo "== acceptance manifest =="
cat acceptance/manifest.json
if [ "$suite_status" -ne 0 ]; then
    exit "$suite_status"
fi
if [ "$manifest_status" -ne 0 ]; then
    exit "$manifest_status"
fi
