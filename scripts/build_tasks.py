#!/usr/bin/env python3
"""Write the eight task briefs. Identical text goes to every candidate (no hints)."""
from __future__ import annotations

import pathlib

BENCH = pathlib.Path(__file__).resolve().parent.parent
TASKS = BENCH / "tasks"

PREAMBLE = """# BENCH-MODEL-001 / {tid} — {title}

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

{deliverables}

## Stop conditions

{stops}
"""

BRIEFS: dict[str, dict[str, str]] = {
    "T1": {
        "title": "Requirements interpretation and solution planning",
        "deliverables": "`plan.md` — the implementation-oriented solution plan, structured with "
                        "clear headings, plus a short `plan-assumptions.md` listing every assumption "
                        "you had to make.",
        "stops": "Stop when `plan.md` covers every required area below and every recommendation is "
                 "traceable to the facts in FACTS.md or is explicitly labelled as an assumption. "
                 "Do not write code.",
        "body": """
## Scenario

A business wants one governed enterprise AI application that lets employees query the
Knowledge and Data they are authorised to use. The inputs are ERP databases, a data
warehouse, PostgreSQL and SQL Server instances, object storage, company documents,
policies and SOPs. Answers come from an LLM.

The product has three administration planes and they must not be blurred:

1. **OpenJM operator control plane** — our staff: tenancy, entitlements, connectors,
   platform-wide policy.
2. **Customer organisation administration plane** — the customer's own administrators:
   their users, groups, data sources, permissions.
3. **End-user experience** — employees asking questions and reading answers.

`FACTS.md` in this directory is the authoritative description of what exists today and what
is contractually required. Read it first.

## Task

Produce an implementation-oriented solution plan for connecting these sources into the
governed application. It must cover, each in its own section:

- functional requirements;
- nonfunctional requirements (performance, cost, availability, privacy, operability);
- data ingestion and connectors;
- knowledge ingestion and permission-aware retrieval;
- classification and role enforcement;
- tenant isolation;
- auditing and operational monitoring;
- approval and confirmation boundaries (what the system may do unattended vs what needs a
  human);
- testing and acceptance;
- deployment and rollback;
- dependencies, sequencing and bounded work packages.

A plan that invents capabilities we do not have, or that contradicts FACTS.md, is worse than
a plan that says "this needs to be built". Mark clearly which parts are new work, which are
extension of what exists, and which are configuration-only. Generic AI architecture lectures
that do not engage with the three administration planes, the per-tenant boundary or the
classification model will be scored accordingly.
""",
    },
    "T2": {
        "title": "Work-package framing for a permission-change defect",
        "deliverables": "`work-package.md` — a bounded implementation package for a coding agent, "
                        "plus `evidence.md` with the exact files and line references you inspected.",
        "stops": "Stop when the package is specific enough that another engineer could implement it "
                 "without asking you a question. Do not implement the change.",
        "body": """
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
""",
    },
    "T3": {
        "title": "Backend feature implementation",
        "deliverables": "The implemented feature in `src/reportcore/service.py`, tests you add "
                        "under `tests/`, and `notes.md` describing your design decisions and how to "
                        "reproduce your verification.",
        "stops": "Stop when `sh run_checks.sh` passes and `SavedReportsService` implements every "
                 "documented behaviour. Two bounded correction cycles after your first full test "
                 "run are allowed; record whether your first run passed.",
        "body": """
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
""",
    },
    "T4": {
        "title": "Frontend UX and administrative safety",
        "deliverables": "The corrected screen (`public/index.html`, `public/app.js`, "
                        "`public/styles.css` as needed), the tests you add under `tests/`, and "
                        "`notes.md` with your test command and its output. A `screenshot.png` is "
                        "welcome if your tooling can produce one.",
        "stops": "Stop when the screen honours every behaviour listed below and your tests cover "
                 "them. Record the exact commands you ran.",
        "body": """
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
""",
    },
    "T5": {
        "title": "Security, authorization and tenant isolation",
        "deliverables": "The corrected source in `src/reportcore/`, negative authorization tests "
                        "you add under `tests/`, and `findings.md` with one entry per defect: what it "
                        "is, impact, the evidence that shows it, the fix, and the test that now "
                        "covers it.",
        "stops": "Stop when you have fixed every defect you can demonstrate, `sh run_checks.sh` "
                 "passes, and findings.md covers each fix. Two bounded correction cycles are allowed "
                 "after your first full test run.",
        "body": """
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
""",
    },
    "T6": {
        "title": "CI diagnosis and bounded repair",
        "deliverables": "The repaired tree, and `root-cause.md` with: the evidence you inspected, "
                        "the root cause of each problem, your change, the focused verification you ran "
                        "(commands and output), and whether your first attempt succeeded or needed a "
                        "second correction cycle.",
        "stops": "Stop when `sh run_ci.sh` satisfies every clause of the CI contract in `README.md` "
                 "and the suite genuinely passes. At most two bounded correction cycles after your "
                 "first test run; record which attempt fixed it.",
        "body": """
## Scenario

`cifix/` in this directory is the `tally` package with its CI entry point. The release gate
reads `run_ci.sh`'s exit status and `acceptance/manifest.json`. Something is wrong: the gate
reported the build as passing, but the acceptance record and the actual test results do not
agree, and one check that appears to succeed is not evidence of anything.

`README.md` states the CI contract precisely. Read it before changing anything.

## Task

- Inspect the failure evidence and identify the underlying cause or causes.
- Apply the smallest justified correction.
- Run focused verification and prove the required acceptance state.
- Document root cause and resolution.

Hard constraints:

- do not skip, delete, weaken or retarget failing tests;
- do not increase retries or add tolerance to make a test pass;
- do not remove or bypass a blocking gate;
- do not manufacture a passing manifest: what is recorded must be the truth of the run that
  happened;
- do not change unrelated functionality;
- `sh run_ci.sh` must exit non-zero whenever any test fails, and `0` only when the suite
  genuinely passed;
- an interrupted or partial nested run must not be reported as a success.
""",
    },
    "T7": {
        "title": "Independent code review",
        "deliverables": "`review.md` — the review report, in the structure the diff document asks for.",
        "stops": "Stop when every finding you intend to raise has a file, a location, a severity and "
                 "supporting evidence. Do not modify the diff or the code.",
        "body": """
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
""",
    },
    "T8": {
        "title": "Test design and acceptance engineering",
        "deliverables": "The tests you add under `tests/`, and `test-plan.md` explaining what each test "
                        "claims, how it would detect the claim being false, and any remaining coverage "
                        "gaps you know of.",
        "stops": "Stop when your suite runs with `PYTHONPATH=src python3 -m unittest discover -s tests` "
                 "and each test fails when the claim it covers is false. Two bounded correction cycles "
                 "are allowed.",
        "body": """
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
""",
    },
}

FACTS = """# FACTS.md — what exists today, and what is contractually required

Authoritative for T1. If a plan needs something outside this list, it must say so explicitly
instead of assuming it exists.

## Deployed and working (production)

- Multi-tenant SaaS on Ubuntu 24.04, PostgreSQL 16.15, Keycloak 26.7.4 for SSO, Node 22 and
  Python 3.11 services, deployed as a non-root `openjm` user.
- Every request carries a tenant claim; row-level tenant scoping is enforced in application
  code and covered by tests. Customer data for one tenant is never visible to another.
- Keycloak realms per tenant, OIDC with PKCE, group-to-role mapping: roles are
  `viewer` < `analyst` < `admin`, plus platform-operator roles that customers never see.
- An audit table records actor, tenant, action, object and detail for every write and every
  privileged read; audit rows are append-only.
- Workspaces: a named container that groups a customer's folders and resources. Workspace
  membership is the coarse authorization unit today.
- Document ingestion for PDF/DOCX up to 25 MB into object storage, with text extraction and
  a per-document classification of `internal` or `confidential`. Chunking and embeddings are
  **not** in production.
- A retrieval service that searches **whole documents** with PostgreSQL full-text search,
  filtered by workspace membership; there is no vector store in production.
- Connectors: a REST source connector for JSON APIs. No ERP, warehouse, SQL Server or
  object-storage connectors exist yet.
- Operational monitoring: structured logs, Prometheus metrics for request latency and error
  rates, and an alert on failed background jobs.
- CI: GitHub Actions with build, unit and integration tests, a container build and a signed
  release; every merge requires review and green checks.

## Contractual and business requirements

- Customer data stays within the customer's region; no cross-tenant training, no cross-tenant
  retrieval. A tenant administrator can request a data export; a deletion request must remove
  content and embeddings within 30 days.
- Every answer that a user can act on must be traceable to the sources it used, and answers
  that the system is not confident about must say so rather than guess.
- Confidential documents are readable only by tenant administrators, never by `viewer` or
  `analyst`, regardless of workspace membership.
- The operator plane must be able to suspend a tenant, rotate a connector credential and see
  per-tenant usage without being able to read customer content.
- Customer administrators manage their own users, groups and data sources, and cannot see or
  change anything belonging to another customer.
- Administrative changes to access must be deliberate, audited, and reversible.

## Explicitly not available

- No vector database, no embedding pipeline, no reranking in production.
- No ERP (SAP/NetSuite/Dynamics), data-warehouse (Snowflake/BigQuery/Redshift), SQL Server or
  object-storage connector.
- No policy engine beyond Keycloak roles and workspace membership; no document-level ACLs
  beyond the `internal`/`confidential` classification.
- No managed LLM gateway: model access is per-provider API keys today.
- No agentic automation in the product; there is no approval workflow framework to reuse.
"""


def main() -> None:
    TASKS.mkdir(parents=True, exist_ok=True)
    (TASKS / "FACTS.md").write_text(FACTS)
    for tid, spec in BRIEFS.items():
        text = PREAMBLE.format(tid=tid, title=spec["title"], deliverables=spec["deliverables"],
                               stops=spec["stops"])
        (TASKS / f"{tid}.md").write_text(text + spec["body"].strip() + "\n")
    print("wrote", len(BRIEFS), "briefs + FACTS.md to", TASKS)


if __name__ == "__main__":
    main()
