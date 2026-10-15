#!/bin/sh
# CI entry point for the tally package. The release gate reads this script's exit status
# and acceptance/manifest.json.
#
# Reads:  tests/
# Writes: acceptance/run.log, acceptance/summary.txt, acceptance/manifest.json
echo "== running the tally suite =="
# Capture the suite's own exit status before anything else can mask it. The old pipeline
# (`python3 ... | tee acceptance/run.log | grep ...`) reported grep's status, and the
# trailing `cat` always reported 0, so a failing suite still exited 0.
python3 -m unittest discover -s tests -t . -v > acceptance/run.log 2>&1
tests_status=$?
cat acceptance/run.log
grep -E "^(OK|FAILED)" acceptance/run.log > acceptance/summary.txt
python3 tools/write_manifest.py acceptance/summary.txt
manifest_status=$?
echo "== acceptance manifest =="
cat acceptance/manifest.json
# Exit 0 only when the whole suite genuinely passed; anything else is a failure the gate
# must see.
if [ "$tests_status" -ne 0 ] || [ "$manifest_status" -ne 0 ]; then
    echo "== CI FAILED =="
    exit 1
fi
exit 0
