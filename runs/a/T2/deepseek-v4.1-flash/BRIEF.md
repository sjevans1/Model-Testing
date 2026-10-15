# BENCH-MODEL-001 / T2 — Work-package framing for a permission-change defect

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

`work-package.md` — a bounded implementation package for a coding agent, plus `evidence.md` with the exact files and line references you inspected.

## Stop conditions

Stop when the package is specific enough that another engineer could implement it without asking you a question. Do not implement the change.
## Scenario

`adminaccess/` in this directory is the current admin console slice. `web/users.js` posts a
role change to the API the moment an administrator picks a different option in the dropdown,
so access levels change with no explicit confirmation step. Support has seen accidental
privilege changes.

Read the supplied implementation before you write anything.

## Task

Prepare a bounded implementation package that fixes this behaviour without redesigning the
application. The package must state:

- what changes, in which files, and why those are the right boundaries;
- the intended state transition (current role -> staged role -> applied role, including what
  happens on failure);
- explicit Save/Apply and Cancel/Discard semantics;
- how stale updates are handled (the service exposes a per-user `version`);
- what server-side authorization the change requires, and why the frontend cannot be the
  boundary;
- the audit expectation for an applied change;
- the regression tests to add, named and specific;
- migration and compatibility risks;
- exact acceptance conditions and stop conditions;
- an explicit list of what must remain unchanged.

Cite the files and line numbers you actually inspected. Recommendations that would break
existing behaviour described in the repository are scored down.
