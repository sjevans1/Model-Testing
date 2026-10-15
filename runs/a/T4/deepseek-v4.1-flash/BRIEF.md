# BENCH-MODEL-001 / T4 — Frontend UX and administrative safety

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

The corrected screen (`public/index.html`, `public/app.js`, `public/styles.css` as needed), the tests you add under `tests/`, and `notes.md` with your test command and its output. A `screenshot.png` is welcome if your tooling can produce one.

## Stop conditions

Stop when the screen honours every behaviour listed below and your tests cover them. Record the exact commands you ran.
## Scenario

`adminui/` in this directory is the user-access screen of the tenant portal. As shipped, the
role dropdown persists a change the instant it changes, has no explicit apply step, no
confirmation for privilege-sensitive changes, no loading state, no duplicate-submit guard,
and it reports "Saved." even when the request failed.

## Task

Rework the interaction so an administrator's change is staged, reviewable and deliberate.
`README.md` freezes the DOM contract (ids) and the mock API; other teams' tests depend on
those ids, so keep them.

Required behaviour:

- changing the dropdown stages a local pending change and sends nothing;
- the pending change is visibly identifiable;
- an explicit Apply/Save control commits it, and a Cancel/Discard control discards it;
- a change that grants or removes `admin` requires an explicit in-page confirmation before
  it can be applied (in-page, not a browser dialog, so it can be driven by automated tests:
  the confirmation control carries `data-confirm="yes"` inside `#confirm-<id>`);
- a loading state is visible while a submission is in flight and the apply control cannot be
  activated again;
- success and failure are reported distinctly, and a failure never claims success and never
  silently drops the staged change;
- a stale-version conflict (HTTP 409) is surfaced to the administrator;
- the controls have accessible names and the status/error regions are live regions;
- the layout does not overflow a 390px-wide viewport.

Add tests. A browser-driven test is the strongest evidence; `lightpanda` is on PATH.
