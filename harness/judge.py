#!/usr/bin/env python3
"""Model-blind qualitative scoring for the document tasks (T1, T2, T7).

    python3 harness/judge.py --prepare      # anonymise queued deliverables
    python3 harness/judge.py --run          # score them with GLM-5.3 Flash
    python3 harness/judge.py --report       # show the per-artifact scores

The evaluator is GLM-5.3 Flash through OpenCode Go, as the assignment permits for
qualitative judgement. It never sees which candidate produced a deliverable: payloads are
scrubbed of candidate identities and written under an opaque id, and the id -> (task,
candidate) map lives in a separate file the judge prompt never contains.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import uuid

BENCH = pathlib.Path(__file__).resolve().parent.parent
QUEUE = BENCH / "judge_queue"
ANON = QUEUE / "anon"
RESULTS = BENCH / "judge_results"
MAP = QUEUE / "map.json"
JUDGE_MODEL = "glm-5.3-flash"
JUDGE_PROVIDER = "opencode-go"

IDENTITY = re.compile(r"\b(claude|haiku|gpt-6|gpt5|glm|deepseek|luna|openai|anthropic|"
                      r"opencode|model[- ]blind|BENCH-MODEL)\b", re.I)

RUBRICS = {
    "T1": """You are scoring a solution plan written for a governed multi-tenant enterprise AI
product. The brief asked for one plan covering: functional requirements; nonfunctional
requirements; data ingestion and connectors; knowledge ingestion and permission-aware
retrieval; classification and role enforcement; tenant isolation; auditing and operational
monitoring; approval and confirmation boundaries; testing and acceptance; deployment and
rollback; dependencies, sequencing and bounded work packages. Three administration planes
(operator, customer admin, end user) had to stay distinct, and the plan had to stay inside
the FACTS document instead of inventing capabilities.

Score 0-100 for each category:
- functional: requirements coverage, technical credibility, alignment with the stated business
  problem and the FACTS constraints, no invented capabilities.
- security: how well tenant isolation, classification enforcement, audit and fail-closed
  behaviour are specified.
- instruction: adherence to the required structure and the "mark assumptions" instruction.
- maintainability: boundedness of the work packages, dependency clarity, sequencing, phasing.
- testing: quality of the testing/acceptance plan and its traceability to requirements.
- efficiency: signal per page. Penalise padding, repetition and generic AI-architecture
  filler; reward a dense plan that says less but commits to more.
""",
    "T2": """You are scoring a work-package specification for a bounded defect fix. The defect:
an admin console persisted a role change the moment the dropdown changed, with no explicit
confirmation. The package had to describe: what changes and in which files; affected frontend
and backend boundaries; the intended state transition; explicit Save/Apply and Cancel
behaviour; stale-update handling (the service exposes a per-user version); the required
server-side authorization and why the frontend is not the boundary; the audit expectation;
named regression tests; migration/compatibility risk; exact acceptance and stop conditions;
and an explicit list of what must remain unchanged. It had to cite the files it inspected.

Score 0-100 for each category:
- functional: is the package implementation-ready, correct about the boundaries, and specific
  enough for another engineer to execute without questions? Are its citations real?
- security: server-side authorization, stale/concurrent update safety, audit treatment, and
  any risk of the fix being bypassable from the client.
- instruction: adherence to the requested package structure and stop conditions.
- maintainability: scope discipline; does it avoid redesigning what it was told not to?
- testing: the regression tests it names, and whether they would catch the regression.
- efficiency: signal per page; penalise restating the problem or padding.
""",
    "T7": """You are scoring an independent code review of an anonymised pull request against a
tenant role-management service. The product requires: a role can only be changed inside the
user's own tenant; only administrators may change a role; administrative actions are audited;
and replaying the same action twice must not apply it twice. The diff contains genuine defects
(cross-tenant and cross-user role changes, a bypass of the request/approve workflow without
authorization, a lost role validation, a pending-request listing that ignores tenants, a batch
operation that reports completion it did not achieve, and deleted negative tests) as well as
legitimate design decisions that must NOT be flagged.

Score 0-100 for each category:
- functional: did the review find the real defects, with correct file and line references, and
  did it avoid inventing problems? False positives on legitimate changes are as costly as
  missed defects.
- security: correct severity on the security defects, and whether the tenant-boundary and
  authorization failures are called blocking.
- instruction: adherence to the requested report structure (blocking/non-blocking, locations,
  severity, evidence, remediation, uncertainty, rejected findings, merge recommendation).
- maintainability: is the remediation actionable and proportional?
- testing: did it notice the weakened/deleted negative tests and the missing coverage?
- efficiency: signal per page; a long list of speculative findings scores badly.
""",
}

PROMPT = """{rubric}

Score the artifact below. Reply with ONLY a JSON object, no prose before or after:

{{"functional": <0-100>, "security": <0-100>, "instruction": <0-100>,
  "maintainability": <0-100>, "testing": <0-100>, "efficiency": <0-100>,
  "critical_failures": [], "rationale": "<at most 80 words>"}}

`critical_failures` lists ONLY these, and they must be evident in the artifact itself:
fabricated evidence or test output (invented commands, results or logs); claiming behaviour the
artifact plainly does not contain; recommending a prohibited production or repository change
(merging, deploying, pushing to a production branch, touching live infrastructure, or weakening
a mandatory gate). A design disagreement, a different HTTP status code, a missing section, a
stylistic or severity disagreement, or an incomplete deliverable is NOT a critical failure:
score it in the relevant category instead. Use an empty list when none of the above apply.

ARTIFACT
--------
{artifact}
"""


def scrub(text: str) -> str:
    """Remove anything that could identify the candidate model."""
    lines = []
    for line in text.splitlines():
        if IDENTITY.search(line):
            line = IDENTITY.sub("[redacted]", line)
        lines.append(line)
    return "\n".join(lines)


def prepare() -> None:
    ANON.mkdir(parents=True, exist_ok=True)
    existing = json.loads(MAP.read_text()) if MAP.exists() else {}
    for path in sorted(QUEUE.glob("*.txt")):
        task, _, label = path.stem.partition("__")
        if task not in RUBRICS:
            continue
        if any(v.get("file") == path.name for v in existing.values()):
            continue
        token = uuid.uuid4().hex[:12]
        (ANON / f"{token}.txt").write_text(scrub(path.read_text()))
        existing[token] = {"task": task, "label": label, "file": path.name}
    MAP.write_text(json.dumps(existing, indent=2, sort_keys=True))
    print(f"prepared {len(existing)} anonymised artifacts in {ANON}")


def run_judge(limit: int = 0) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    mapping = json.loads(MAP.read_text()) if MAP.exists() else {}
    for token, meta in sorted(mapping.items()):
        out = RESULTS / f"{token}.json"
        if out.exists():
            continue
        if limit and len(list(RESULTS.glob("*.json"))) >= limit:
            break
        artifact = (ANON / f"{token}.txt").read_text()[:28000]
        prompt = PROMPT.format(rubric=RUBRICS[meta["task"]], artifact=artifact)
        usage = RESULTS / f"{token}.usage.json"
        cmd = ["hermes", "-z", prompt, "-m", JUDGE_MODEL, "--provider", JUDGE_PROVIDER,
               "--in", str(BENCH), "--usage-file", str(usage), "--yolo"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                              cwd=str(BENCH))
        text = proc.stdout.strip()
        match = re.search(r"\{.*\}", text, re.S)
        try:
            scores = json.loads(match.group(0)) if match else {}
        except ValueError:
            scores = {}
        scores["_task"] = meta["task"]
        scores["_label"] = meta["label"]
        out.write_text(json.dumps(scores, indent=2))
        print(f"{token} {meta['task']} {meta['label']}: "
              f"{ {k: scores.get(k) for k in ('functional', 'security', 'instruction')} }", flush=True)


def report() -> None:
    results = []
    for path in sorted(RESULTS.glob("*.json")):
        if path.name.endswith(".usage.json"):
            continue
        data = json.loads(path.read_text())
        results.append((data.get("_task"), data.get("_label"), data))
    for task, label, data in sorted(results):
        cats = " ".join(f"{k}={data.get(k)}" for k in
                        ("functional", "security", "instruction", "maintainability",
                         "testing", "efficiency"))
        print(f"{task:3} {label:22} {cats}")
    print(f"{len(results)} judged artifacts")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if args.prepare or not (args.run or args.report):
        prepare()
    if args.run:
        run_judge(args.limit)
    if args.report:
        report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
