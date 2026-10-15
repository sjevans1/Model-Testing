# BENCH-MODEL-001 — status and continuation note

Written by the orchestrator when the working session reached its iteration budget. Everything
below is the real state on disk; nothing is estimated.

## What is finished and verified

1. **Preflight** (`preflight/`)
   - All three candidates exist on the OpenCode Go relay: `opencode.ai/zen/go/v1/models`
     returns `claude-haiku-5-5`, `gpt-6-luna`, `deepseek-v4.1-flash` (37 models total; the
     listing carries no pricing or context metadata).
   - One tool-capable connectivity probe per candidate (create a file, run `wc -c`, report it):
     all three returned `12 probe.txt` / `READY`.
   - Token/cache telemetry works: `hermes -z --usage-file` writes input/output/cache-read/
     cache-write/reasoning tokens, API calls, session id, and doom-flag fields
     (`completed`, `partial`, `interrupted`, `turn_exit_reason`).
   - Official OpenCode Go rate card captured (see `harness/driver.py::RATES` for the exact
     numbers used).
   - **Blocking integration finding:** this Hermes build routes `claude-haiku-5-5` on
     `opencode-go` to the OpenAI wire, the relay rejects it with `ModelProtocolUnsupported`,
     and Hermes silently falls back (observed: usage ledger reported
     `model=deepseek/deepseek-v4.1-flash provider=openrouter`). Root cause is a missing
     `claude-*` entry in `hermes_cli/models.py::_OPENCODE_API_MODE_PREFIXES["opencode-go"]`.
     Go serves Haiku only on `/messages`, which requires `x-api-key` (Bearer returns
     401 `Go requires a credential`). Upstream `origin/main` / v0.22.1 already fixes the table.
     The benchmark therefore declares an equivalent anthropic-wire route in its **isolated**
     benchmark home only (`hermes-home/config.yaml`, provider `go-anthropic`). Details:
     `limitations.md` §1.

2. **Fixtures, frozen and validated** (`fixtures/`, `scripts/`)
   - `reportcore_t3` (feature stub), `reportcore_t5` / `reportcore_t8` (same service with eight
     seeded defects, visible smoke tests green so the defects stay hidden), `cifix` (CI runner
     that misreports the overall result), `adminui` (access screen that persists on dropdown
     change), `adminaccess` (work-package source), `review_diff` (anonymised PR diff with
     seeded defects and legitimate decisions).
   - Each fixture was validated before any candidate ran: the hidden suite must fail on the
     shipped tree and pass on a reference implementation. Evidence:
     `task-evidence/reference-validation/README.md`.
     * reportcore: shipped stub 2/13, defective 4/13 (all eight seeded defects caught),
       reference 13/13, and the defective trees keep their visible smoke tests green.
     * cifix: shipped 1/6, reference fix 6/6.
     * adminui: shipped 1/9, reference 9/9 (one scenario reports SKIPPED — see limitations §6).
   - Hidden assets live only in `harness/hidden/` and are never copied into a candidate tree.

3. **Harness** (`harness/`)
   - `driver.py` — one fresh session per trial, isolated `HERMES_HOME`, no fallback provider,
     process-group kill on timeout, one automatic retry on a stalled/killed trial, per-candidate
     `$1.50` metered-equivalent ceiling, rotated execution order, per-trial record in `runs.jsonl`.
   - `hidden/suite_reports.py` (13 acceptance/negative checks), `hidden/grade_t6.py` (6 checks,
     including a sabotage pass that injects a failing test and a pass that removes one),
     `hidden/grade_t4.py` + `hidden/cdp.py` (a stdlib CDP client that drives lightpanda; every
     scenario restarts the mock API so state cannot leak between scenarios).
   - `grade.py` (per-trial grading into `grading/`), `judge.py` (model-blind qualitative scoring
     with GLM-5.3 Flash over scrubbed payloads), `aggregate.py` (`scores.csv`,
     `grading/summary.json`).

4. **Stage A trials** — see `runs.jsonl` and `runs/a/`. T2 completed for all three candidates;
   T4 and T6 were still executing when the session ended (the driver keeps running in the
   background and appends to `runs.jsonl` as each trial completes).

## What is not finished

- **Stage A:** T4 and T6 for all three candidates were still running or queued.
- **Stage B:** T1, T3, T5, T7, T8 for all three candidates (15 trials) had not started.
- **Stage C:** consistency repeats (conditional in the assignment) had not started.
- **Qualitative judging** had been verified on two artifacts only.
- Consequently `scores.csv` currently covers T2 plus whatever completed afterwards; the
  executive comparison and the role suitability matrix in the final dossier cannot be written
  until the remaining trials exist. No number in this repository is invented to fill that gap.

## How to finish it

```sh
cd ~/bench/model-testing
# 1. confirm Stage A finished (the background driver appends here)
python3 - <<'PY'
import json, pathlib
for line in pathlib.Path("runs.jsonl").read_text().splitlines():
    r = json.loads(line)
    print(r["task"], r["model"], r.get("status"), r.get("elapsed_s"), r.get("metered_equivalents_usd"))
PY
# 2. Stage B (15 trials), then optional Stage C (6 repeats)
python3 harness/driver.py --stage b --timeout 600
python3 harness/driver.py --stage c --timeout 600
# 3. grade, judge, aggregate
python3 harness/grade.py
python3 harness/judge.py --prepare && python3 harness/judge.py --run
python3 harness/aggregate.py
# 4. write the executive comparison + role suitability matrix from grading/summary.json,
#    then commit and push
```

A retried trial supersedes its earlier attempt: `grade.py` and `aggregate.py` both keep only
the last record per (task, candidate).

## Standing constraints observed

No production repository, branch, credential, deployment, model-routing setting, review gate or
CI control was changed. Candidate trees have no git remote, so nothing could be pushed from
inside a trial. The only configuration added anywhere is the benchmark-scoped provider entry in
`hermes-home/config.yaml`, which lives inside this directory and affects nothing else.
