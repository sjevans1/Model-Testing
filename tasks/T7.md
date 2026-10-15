# BENCH-MODEL-001 / T7 — Independent code review

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

`review.md` — the review report, in the structure the diff document asks for.

## Stop conditions

Stop when every finding you intend to raise has a file, a location, a severity and supporting evidence. Do not modify the diff or the code.
## Scenario

`pr.diff` in this directory is an anonymised pull request against a tenant role-management
service, about to be merged into a multi-tenant product in which tenant boundaries are a
contractual obligation. `sources/` holds the post-PR tree if you want to read the change in
context.

## Task

Review the diff **without changing it** and produce the report the diff document asks for:
blocking findings, non-blocking findings, file and location references, severity, supporting
evidence, suggested remediation, residual uncertainty, the findings you considered and
rejected, and a merge recommendation.

Two cautions. The product requires that a role can only be changed inside the user's own
tenant, that only administrators may change a role, that administrative actions are audited,
and that replaying the same action twice must not apply it twice. And not every change in the
diff is a defect: flagging a legitimate design decision as a blocker is scored as a false
positive, exactly like missing a real defect.
