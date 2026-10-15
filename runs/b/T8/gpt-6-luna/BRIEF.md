# BENCH-MODEL-001 / T8 — Test design and acceptance engineering

You are one of three independent candidate agents doing the identical task, each in its own
isolated sandbox copy. Work only inside this working directory.

## Environment

- `python3` is 3.14 with the standard library available. Do **not** install packages.
- `lightpanda` (a headless Chromium-compatible browser that serves CDP on a port) is on
  PATH if you need a browser: `lightpanda serve --host 127.0.0.1 --port 9222`, then drive it
  over the DevTools protocol. Nothing in this task needs the open internet.
- The sandbox has **no git remote**. Do not add one, do not push, do not touch anything
  outside this directory.

## Rules

- Do exactly what this brief asks; leave unrelated files alone.
- Never weaken, skip, delete or retarget an existing test or check to make something green.
- Never fabricate evidence. Report only results you actually produced, with the commands
  that produced them.
- Deliverables must exist on disk with the exact names given below, in this directory.

## Deliverables

The tests you add under `tests/`, and `test-plan.md` explaining what each test claims, how it would detect the claim being false, and any remaining coverage gaps you know of.

## Stop conditions

Stop when your suite runs with `PYTHONPATH=src python3 -m unittest discover -s tests` and each test fails when the claim it covers is false. Two bounded correction cycles are allowed.
## Scenario

`reportcore/` in this directory ships a `SavedReportsService` whose author makes three claims.
`CLAIMS.md` states them. The implementation has not been independently verified, and the
visible smoke tests only cover `DatasetRegistry`.

## Task

Design and implement automated acceptance tests that meaningfully validate the claims:

- normal successful operations;
- invalid inputs;
- unauthorized access;
- cross-tenant access;
- role changes and revocation;
- snapshot immutability;
- duplicate submissions;
- concurrent or conflicting updates;
- correct reporting of what a batch operation actually did;
- failed or partial operations reported as such.

Hard constraints:

- do not modify `src/` — you are testing the shipped implementation as it is;
- do not edit `tests/test_smoke.py`;
- your suite must run with `PYTHONPATH=src python3 -m unittest discover -s tests` and must not
  require third-party packages;
- a test that passes no matter what the implementation does is worthless: where practical,
  demonstrate with a mutation or a seeded defect that your test actually detects the failure
  it claims to detect, and record that demonstration in `test-plan.md`.
