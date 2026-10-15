# BENCH-MODEL-001 / T3 — Backend feature implementation

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

The implemented feature in `src/reportcore/service.py`, tests you add under `tests/`, and `notes.md` describing your design decisions and how to reproduce your verification.

## Stop conditions

Stop when `sh run_checks.sh` passes and `SavedReportsService` implements every documented behaviour. Two bounded correction cycles after your first full test run are allowed; record whether your first run passed.
## Scenario

`reportcore/` in this directory is a multi-tenant backend. `DatasetRegistry` is implemented;
`SavedReportsService` is a stub for the feature you are asked to build.

## Task

Implement Saved Reports in `src/reportcore/service.py`:

- persist an immutable snapshot of the report payload (canonical JSON plus sha256 content
  hash, stored next to the report row);
- associate the report and the snapshot with the correct tenant and owner, taken from the
  authenticated actor (never from the payload);
- support authorised retrieval and listing;
- support revocation that never changes or deletes the stored snapshot;
- prevent cross-tenant reads and writes;
- record audit information for the operations that need it;
- return appropriate authorization and validation errors;
- add meaningful automated tests of your own.

Constraints:

- keep the public signatures already present: `save_report(actor, name, payload,
  classification="internal") -> str`, `get_report(actor, report_id) -> dict`,
  `list_reports(actor) -> list[dict]`, `revoke_report(actor, report_id, reason="") -> None`;
- follow the conventions the repository documents and demonstrates in `DatasetRegistry`;
- keep the existing tests green (`tests/test_smoke.py` must not be edited);
- standard library only.

`src/reportcore/README.md` documents the conventions, and the error types are in
`src/reportcore/errors.py`.
