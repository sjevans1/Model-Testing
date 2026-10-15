# BENCH-MODEL-001 / T1 — Requirements interpretation and solution planning

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

`plan.md` — the implementation-oriented solution plan, structured with clear headings, plus a short `plan-assumptions.md` listing every assumption you had to make.

## Stop conditions

Stop when `plan.md` covers every required area below and every recommendation is traceable to the facts in FACTS.md or is explicitly labelled as an assumption. Do not write code.
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
