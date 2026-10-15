# BENCH-MODEL-001 — controlled three-model capability benchmark

Independent comparison of three models for development roles across OpenJM Enterprise AI,
Workspace-Platform and future OpenJM software work:

| Candidate | OpenCode identifier | Route used |
|---|---|---|
| Claude Haiku 5.5 | `claude-haiku-5-5` | `go-anthropic` (declared anthropic-wire route to the same relay — see `limitations.md` §1) |
| GPT-6 Luna | `gpt-6-luna` | `opencode-go` |
| DeepSeek V4.1 Flash | `deepseek-v4.1-flash` | `opencode-go` |

The orchestrator (Hermes) prepared the environment, dispatched one fresh session per
(task, candidate), graded the results with hidden acceptance tests, and scored them against a
fixed rubric. No production repository, branch, credential, deployment or routing setting was
changed.

## Reproduce

```sh
python3 scripts/build_reportcore.py        # multi-tenant backend fixtures (T3, T5, T8)
python3 scripts/build_ci_and_admin.py      # fixtures for T2, T6, T7
python3 scripts/build_adminui.py           # frontend fixture (T4)
python3 scripts/build_tasks.py             # the eight frozen briefs + FACTS.md
python3 harness/driver.py --stage a        # T2, T4, T6 x 3 candidates
python3 harness/driver.py --stage b        # T1, T3, T5, T7, T8 x 3 candidates
python3 harness/grade.py                   # deterministic grading into grading/
python3 harness/judge.py --prepare --run   # model-blind qualitative scoring (T1, T2, T7)
python3 harness/aggregate.py               # scores.csv + grading/summary.json
```

Every fixture is validated against a reference implementation: the hidden suites must fail on
the shipped/defective tree and pass on the reference. Those pairs are recorded in
`task-evidence/reference-validation/`.

## Layout

```
tasks/            the eight frozen briefs (identical for every candidate) + FACTS.md
fixtures/         the fixture trees, one per task (pristine; candidates work on copies)
harness/          driver, graders, judge, aggregation
harness/hidden/   acceptance suites and graders — never copied into a candidate tree
harness/reference/ correct implementations used to prove each fixture is solvable
hermes-home/      the isolated benchmark home (no fallback provider, no plugins/skills)
runs/             per-trial: brief, candidate tree copy, stdout, stderr, usage ledger
grading/          per-trial grading records
judge_queue/      anonymised payloads handed to the qualitative evaluator
task-evidence/    logs, diffs, and fixture-validation evidence
runs.jsonl        one structured record per trial
scores.csv        comparable numeric results
summary.json      machine-readable roll-up (grading/summary.json)
```

## Controls applied

- One fresh Hermes session per trial; the same brief text, fixtures, tool permissions, turn
  budget (`agent.max_turns: 60`), reasoning flag (`medium`) and sandbox for every candidate.
- Sequential execution (never concurrent) so provider contention does not distort latency, with
  the candidate order rotated per task.
- No fallback provider in the benchmark home: a candidate cannot be silently substituted. Each
  trial records the model the usage ledger actually reports and flags `substituted` when it
  differs from the requested id.
- Frozen fixtures, frozen prompts and frozen scoring rules: nothing was retuned after seeing a
  candidate's result.
- Multi-tenant, cross-tenant, privilege and fail-closed checks are hidden from candidates; a
  candidate cannot see the expected values, and the graders run on a scratch copy afterwards.
- Reference implementations prove every fixture is solvable and every grader discriminating.

## Reading the numbers

`overall_score` is out of 100 with the documented maximums: functional correctness 35,
security and data governance 25, instruction adherence 15, testing and evidence 10,
maintainability 10, resource efficiency 5. Where a task could not exercise a category (for
example, T1 has no executable tests), the weight is redistributed in proportion across the
categories that were scored, and the trial record names the redistributed categories.

A trial with a critical failure (unauthorized cross-tenant operation, privilege escalation,
a weakened gate, fabricated evidence, or a success claim for behaviour that demonstrably fails)
keeps its raw score but is excluded from qualification, per the assignment's override.

Cost is metered-equivalent consumption computed from the published OpenCode Go rate card, not
billed spend; Hermes reports no pricing for that relay. See `limitations.md` §3.
