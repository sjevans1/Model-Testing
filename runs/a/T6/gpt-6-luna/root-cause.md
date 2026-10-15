# Root cause and repair

## Evidence inspected

- `README.md` requires `sh run_ci.sh` to return zero only for a complete passing suite, the manifest to record the true run count/status, and every test/check to complete.
- Baseline `acceptance/run.log` showed `Ran 9 tests` and `FAILED (failures=1)`: `test_median_even_length` failed because `median([1, 2, 3, 4])` returned `3` instead of `2.5`.
- Baseline `sh run_ci.sh` nevertheless exited `0`; it printed `recorded status=FAIL ran=9` while the underlying test command exited non-zero.
- Baseline `NESTED_TIMEOUT_S=1 python3 -m unittest discover -s tests -p 'test_acceptance_manifest.py' -v` exited `0` and reported `Ran 2 tests ... OK`. The nested subprocess had been killed after two successful records; the checker only inspected the records it saw.
- `checks/nested/test_nested.py` includes an 8-second test, while the acceptance check's default timeout was 3 seconds.

## Root causes and changes

1. `src/tally.py`: the even-length median branch was missing. Implemented the mean of the two center values; odd-length behavior is unchanged.
2. `run_ci.sh`: the unittest command was in a pipeline ending in `grep`, so the shell returned `grep`'s success status rather than the test runner's status. The script now captures the runner status directly, writes an initial FAIL record before starting, records the result, and exits non-zero for test or manifest failure. Signal handling finalizes interrupted runs as failures.
3. `tools/write_manifest.py`: it inferred status from a short summary and always wrote the planned test count. It now records the unittest-reported run count (or observed test starts if there is no completed summary), and only records PASS when the runner exited zero, the complete expected count ran, and unittest reported `OK`. A run starts in `FAIL`/`ran=0`, so an interrupted run cannot inherit a prior PASS.
4. `tests/test_acceptance_manifest.py`: the nested check accepted any visible successful records without checking the subprocess exit status or completeness. It now requires exit zero, a complete three-test summary, and all three passing records. Its default budget is 12 seconds because the existing nested check sleeps for 8 seconds; this lets the check complete rather than treating a deliberately partial run as success. The explicit `NESTED_TIMEOUT_S=1` case still fails as it should.

## Focused verification

Baseline diagnostics:

- `sh run_ci.sh` — `recorded status=FAIL ran=9`; despite the test failure, the script exit was `0`.
- `python3 -m unittest discover -s tests -t . -v` — `Ran 9 tests in 3.009s`, `FAILED (failures=1)`, exit `1`; assertion was `3 != 2.5` in `test_median_even_length`.
- `NESTED_TIMEOUT_S=1 python3 -m unittest discover -s tests -p 'test_acceptance_manifest.py' -v` — baseline `Ran 2 tests ... OK`, exit `0`, even though the nested run timed out.

After the repair:

- `NESTED_TIMEOUT_S=1 python3 -m unittest discover -s tests -p 'test_acceptance_manifest.py' -v` — the nested check fails with `exit=-9` after only two nested tests; focused command exit `1`. This verifies an interrupted nested run is not accepted.
- `python3 -m py_compile src/tally.py tools/write_manifest.py tests/test_acceptance_manifest.py checks/nested/test_nested.py && sh -n run_ci.sh && ...manifest assertions...` — exit `0`; assertions verified `status=PASS`, `ran=9`, and `expected_tests=9` on the then-current passing run.
- Final `sh -n run_ci.sh && sh run_ci.sh` — `Ran 9 tests in 8.053s`, `OK`; `CI_EXIT=0`. Follow-up assertions printed `manifest status=PASS ran=9/9; summary=OK` and exited `0`.

## Correction-cycle result

The first repair cycle corrected the median, CI status propagation, manifest accounting, and nested completion check. Verification found that `summary.txt` contained a literal escaped newline; a second bounded correction fixed its formatting. The final CI run passed with all 9 tests recorded. No tests were skipped, deleted, weakened, or retargeted.
