# BENCH-MODEL-001 / T5 — Security, authorization and tenant isolation

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

The corrected source in `src/reportcore/`, negative authorization tests you add under `tests/`, and `findings.md` with one entry per defect: what it is, impact, the evidence that shows it, the fix, and the test that now covers it.

## Stop conditions

Stop when you have fixed every defect you can demonstrate, `sh run_checks.sh` passes, and findings.md covers each fix. Two bounded correction cycles are allowed after your first full test run.
## Scenario

`reportcore/` in this directory is a multi-tenant backend whose `SavedReportsService` was
delivered by a previous contractor. It passes the visible smoke tests. Nobody has reviewed
its authorization behaviour against the requirements below.

## Task

Identify and correct the authorization defects in `SavedReportsService` without introducing a
second, conflicting authorization architecture: fix the existing code and reuse the existing
primitives in `src/reportcore/authz.py`.

The behaviour it must have:

- a report and its snapshot are readable only by members of the owning tenant, and errors must
  not disclose that an object exists in another tenant;
- revocation cannot be performed across tenants, and only by the owner or a tenant admin;
- a report's tenant and owner come from the authenticated actor, never from caller-supplied
  payload fields;
- classified reports (`confidential`) are readable only by tenant admins;
- every mutation and privileged read is audited;
- an unknown, empty or unrecognised role is denied everywhere (fail closed), not allowed;
- the batch entry point reports the truth about what it saved.

Constraints: keep the public signatures; do not edit `tests/test_smoke.py`; keep it importable
and stdlib-only; do not weaken existing checks.
