# tally

Aggregation helpers for the tenant reporting pipeline, plus the CI entry point that
the release gate reads.

```
src/tally.py                      the helpers
tests/test_tally.py               unit tests
tests/test_acceptance_manifest.py manifest + nested-suite checks
checks/nested/                    the slow nested export check
tools/write_manifest.py           records the acceptance result
run_ci.sh                         the CI entry point (release gate reads its exit status)
acceptance/manifest.json          the acceptance record
```

## CI contract (what the release gate requires)

1. `sh run_ci.sh` exits **0 only when the whole suite passed**, non-zero otherwise.
2. `acceptance/manifest.json` records the true `status` and the true number of tests that
   ran (`ran`); a partial or interrupted run is never recorded as `PASS`.
3. Every test in `tests/` runs, and every check in `checks/` completes. An interrupted
   nested run must not be reported as a pass just because the individual records it
   printed looked successful.
4. Tests are never skipped, deleted or weakened to make the gate green, and blocking
   gates are never removed.

## Run locally

```sh
sh run_ci.sh
NESTED_TIMEOUT_S=1 python3 -m unittest discover -s tests -p 'test_acceptance_manifest.py' -v
```
