#!/usr/bin/env python3
"""Deterministic grading for BENCH-MODEL-001.

    python3 harness/grade.py                 # every completed trial in runs.jsonl
    python3 harness/grade.py --task T6       # restrict

For each trial it runs the task's hidden grader against the candidate's work directory and
writes `grading/<task>/<label>.json` with per-check results plus a category score where a
deterministic judgement is possible. Qualitative categories for T1/T2/T7 are left to judge.py
(payloads are written to `judge_queue/`).

Category weights (documented maximums): functional 35, security 25, instruction 15,
testing 10, maintainability 10, efficiency 5.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

BENCH = pathlib.Path(__file__).resolve().parent.parent
HID = BENCH / "harness" / "hidden"
GRADING = BENCH / "grading"
QUEUE = BENCH / "judge_queue"

WEIGHTS = {"functional": 35, "security": 25, "instruction": 15,
           "testing": 10, "maintainability": 10, "efficiency": 5}

# check-id -> category, for the tasks whose graders emit check ids
CHECK_CATEGORY = {
    "T3": {"A01": "functional", "A02": "functional", "A07": "functional",
           "A11": "functional", "A13": "functional",
           "A03": "security", "A04": "security", "A05": "security", "A06": "security",
           "A08": "security", "A10": "security", "A12": "security", "A14": "security"},
    "T5": {"A01": "functional", "A02": "functional", "A07": "functional",
           "A11": "functional", "A13": "functional",
           "A03": "security", "A04": "security", "A05": "security", "A06": "security",
           "A08": "security", "A10": "security", "A12": "security", "A14": "security"},
    "T4": {"S01": "functional", "S02": "functional", "S03": "functional",
           "S05": "functional", "S06": "functional", "S07": "functional",
           "S04": "security", "S08": "instruction"},
    "T6": {"G1": "functional", "G5": "functional",
           "G2": "security", "G3": "security",
           "G6": "instruction", "G4": "testing"},
}

UNTOUCHABLE = {"T3": ["tests/test_smoke.py"], "T5": ["tests/test_smoke.py"],
               "T8": ["tests/test_smoke.py"], "T6": [], "T4": [], "T1": [], "T2": [], "T7": []}
SIGNATURES = ["def save_report", "def get_report", "def list_reports", "def revoke_report"]


GENERATED_DIRS = ("mutation/", "corpus/", "generated/", "mutants/", ".bench-")


def is_generated(rel: str) -> bool:
    return any(rel.startswith(d) or f"/{d}" in rel for d in GENERATED_DIRS)


def source_changes(changed: list[str]) -> list[str]:
    return [c for c in changed if not is_generated(c)]


def read_json(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return {}


def run_hidden(script: str, tree: pathlib.Path, timeout: float = 420) -> list[dict]:
    try:
        proc = subprocess.run([sys.executable, str(HID / script), str(tree)],
                              capture_output=True, text=True, timeout=timeout)
        data = json.loads(proc.stdout or "{}")
        return data.get("results", [])
    except Exception as exc:  # noqa: BLE001
        return [{"id": "harness", "passed": False, "detail": f"{type(exc).__name__}: {exc}",
                 "group": "harness"}]


def baseline(work: pathlib.Path) -> dict:
    return read_json(work / ".bench-fixture-baseline.json")


def changed_files(work: pathlib.Path) -> list[str]:
    """Files the candidate changed or added, using the recorded fixture baseline."""
    import hashlib

    base = baseline(work)
    out = []
    for path in sorted(work.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        if path.name in ("usage.json", "stdout.txt", "stderr.txt", ".bench-fixture-baseline.json"):
            continue
        try:
            rel = path.relative_to(work).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        except OSError:
            continue
        if base.get(rel) != digest:
            out.append(rel)
    return out


def own_tests(work: pathlib.Path) -> tuple[int, bool]:
    """(number of candidate test files, do they run green?)"""
    files = [p for p in list((work / "tests").glob("*")) if p.suffix in (".py", ".js", ".mjs")]
    files = [p for p in files if p.name != "test_smoke.py"]
    if not files:
        return 0, False
    py = [p for p in files if p.suffix == ".py"]
    green = False
    if py:
        env = dict(os.environ, PYTHONPATH="src")
        try:
            proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                                  cwd=str(work), capture_output=True, text=True, timeout=300, env=env)
            green = proc.returncode == 0
        except Exception:  # noqa: BLE001
            green = False
    return len(files), green


t8_two_sided_cache: dict[str, dict] = {}


def heuristic_categories(task: str, work: pathlib.Path, checks: list[dict]) -> dict:
    """Instruction / testing / maintainability from the artifact itself."""
    out: dict[str, tuple[float, str]] = {}
    changed = changed_files(work)
    notes_md = [p for p in ("notes.md", "findings.md", "root-cause.md", "test-plan.md",
                            "work-package.md", "plan.md", "review.md", "evidence.md",
                            "plan-assumptions.md") if (work / p).exists()]
    deliverables = [p.name for p in work.iterdir() if p.is_file() and p.suffix in (".md", ".png")]

    # instruction adherence -----------------------------------------------------------
    penalty = []
    for forbidden in UNTOUCHABLE[task]:
        # exact relative path only: a copy of the same file inside a mutation corpus is not an edit
        if any(c == forbidden for c in source_changes(changed)):
            penalty.append(f"{forbidden} was modified")
    if task in ("T3", "T5"):
        service = (work / "src" / "reportcore" / "service.py")
        text = service.read_text() if service.exists() else ""
        missing = [sig for sig in SIGNATURES if sig not in text]
        if missing:
            penalty.append(f"public signatures missing: {missing}")
    if task == "T8":
        src_changed = [c for c in changed if c.startswith("src/")]
        if src_changed:
            penalty.append(f"src/ was modified although the brief forbids it: {src_changed[:3]}")
    if task == "T4":
        server_changed = [c for c in changed if c == "server.py"]
        if server_changed:
            penalty.append("server.py (the frozen mock API) was modified")
    if not deliverables:
        penalty.append("no markdown deliverable was produced")
    out["instruction"] = (0.0 if penalty else 1.0, "; ".join(penalty) or
                          f"deliverables: {deliverables}")

    # testing -------------------------------------------------------------------------
    n_tests, green = own_tests(work)
    if task == "T8":
        two = t8_two_sided_cache.get(str(work)) or {}
        detects, passes = bool(two.get("fails_on_shipped")), bool(two.get("passes_on_fixed"))
        score = (0.5 * detects + 0.5 * passes)
        if n_tests >= 2:
            score = min(1.0, score + 0.1)
        out["testing"] = (round(score, 3),
                          f"{n_tests} test file(s); detects defects={detects}, passes on a correct "
                          f"implementation={passes} (a suite that fails in this defective tree is "
                          f"expected)")
    elif task in ("T3", "T5", "T4"):
        score = 0.0
        if n_tests:
            score = 0.7 if green else 0.45
            score += 0.3 if n_tests >= 2 else 0.0
        out["testing"] = (min(score, 1.0),
                          f"{n_tests} test file(s) added, suite {'green' if green else 'not green'}")
    else:
        out["testing"] = (0.5, f"{n_tests} test file(s) added (not required by this task)")

    # maintainability -----------------------------------------------------------------
    m_pen = []
    src_changes = source_changes(changed)
    if len(src_changes) > 12:
        m_pen.append(f"{len(src_changes)} source files changed")
    generated = len(changed) - len(src_changes)
    for c in changed:
        if c.endswith(".pyc") or "__pycache__" in c:
            m_pen.append("compiled artifacts left behind")
            break
    third_party = []
    for rel in changed:
        if rel.endswith(".py"):
            text = (work / rel).read_text(errors="replace")
            for mod in re.findall(r"^\s*import (\w+)", text, re.M):
                if mod not in sys.stdlib_module_names and mod not in ("reportcore", "tally",
                                                                      "adminaccess", "cdp",
                                                                      "websocket", "websockets"):
                    third_party.append(f"{rel}:{mod}")
    if third_party:
        m_pen.append(f"non-stdlib imports: {sorted(set(third_party))[:3]}")
    m_note = "; ".join(m_pen) or f"{len(src_changes)} source files changed"
    if generated:
        m_note += f" (+{generated} generated corpus files, not counted)"
    out["maintainability"] = (0.0 if m_pen else 1.0, m_note)
    return out


def category_scores(task: str, checks: list[dict], work: pathlib.Path) -> dict:
    cats: dict[str, list[float]] = {}
    for c in checks:
        cid = c.get("id", "")
        cat = CHECK_CATEGORY.get(task, {}).get(cid)
        if not cat:
            continue
        if c.get("not_applicable") or str(c.get("detail", "")).startswith("SKIPPED"):
            continue
        cats.setdefault(cat, []).append(1.0 if c.get("passed") else 0.0)
    scored = {cat: (sum(v) / len(v), f"{int(sum(v))}/{len(v)} checks")
              for cat, v in cats.items() if v}
    scored.update(heuristic_categories(task, work, checks))
    return scored


def t8_two_sided(work: pathlib.Path) -> dict:
    """A candidate suite must fail on the shipped implementation and pass on a correct one."""
    import shutil
    import tempfile

    ref = BENCH / "harness" / "reference"
    result = {"fails_on_shipped": False, "passes_on_fixed": False, "tests_ran": 0, "notes": ""}
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="t8-"))
    try:
        defective = scratch / "defective"
        shutil.copytree(work, defective, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        fixed = scratch / "fixed"
        shutil.copytree(work, fixed, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(ref / "service_correct.py", fixed / "src" / "reportcore" / "service.py")
        shutil.copy2(ref / "authz_correct.py", fixed / "src" / "reportcore" / "authz.py")

        def run_suite(tree: pathlib.Path) -> tuple[int, int, str]:
            env = dict(os.environ, PYTHONPATH="src")
            proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                                  cwd=str(tree), capture_output=True, text=True, timeout=600, env=env)
            text = proc.stdout + proc.stderr
            m = re.search(r"Ran (\d+) tests?", text)
            return proc.returncode, int(m.group(1)) if m else 0, text

        rc_def, n_def, _ = run_suite(defective)
        rc_fix, n_fix, out_fix = run_suite(fixed)
        result["tests_ran"] = n_fix
        # the candidate's own tests must FAIL while src is still the shipped implementation
        result["fails_on_shipped"] = rc_def != 0 and n_def > 0
        result["passes_on_fixed"] = rc_fix == 0 and n_fix > 0
        if not result["passes_on_fixed"]:
            result["notes"] = out_fix[-400:]
    except Exception as exc:  # noqa: BLE001
        result["notes"] = f"{type(exc).__name__}: {exc}"
    finally:
        import shutil as _sh

        _sh.rmtree(scratch, ignore_errors=True)
    return result


def grade_trial(rec: dict) -> dict:
    task, model = rec["task"], rec["model"]
    work = pathlib.Path(rec.get("workdir", ""))
    label = BENCH.name and rec.get("provider_route") and ""
    label = (rec.get("workdir") or "").rstrip("/").split("/")[-1]
    entry = {"task": task, "model": model, "label": label, "workdir": str(work),
             "status": rec.get("status"), "checks": [], "categories": {},
             "notes": [], "needs_judge": False}
    if not work.exists():
        entry["notes"].append("work directory missing")
        return entry

    if task in ("T3", "T5"):
        entry["checks"] = run_hidden("suite_reports.py", work)
    elif task == "T4":
        entry["checks"] = run_hidden("grade_t4.py", work, timeout=600)
    elif task == "T6":
        entry["checks"] = run_hidden("grade_t6.py", work, timeout=600)
    elif task == "T8":
        two = t8_two_sided(work)
        t8_two_sided_cache[str(work)] = two
        entry["two_sided"] = two
        entry["checks"] = [
            {"id": "M1", "group": "functional", "passed": two["fails_on_shipped"],
             "detail": f"candidate suite fails on the shipped implementation ({two['tests_ran']} tests)"},
            {"id": "M2", "group": "functional", "passed": two["passes_on_fixed"],
             "detail": "candidate suite passes when a correct implementation is dropped in"},
        ]
        claim_coverage = 0
        text = ""
        for p in (work / "tests").glob("*.py"):
            text += p.read_text(errors="replace")
        for probe in ("tenant", "confidential", "revok", "save_batch", "hash"):
            if probe in text.lower():
                claim_coverage += 1
        entry["checks"].append(
            {"id": "M3", "group": "security", "passed": claim_coverage >= 4,
             "detail": f"{claim_coverage}/5 claim areas referenced by the added tests"})
        entry["categories"] = {
            "functional": (0.5 * two["fails_on_shipped"] + 0.5 * two["passes_on_fixed"],
                           "two-sided mutation result"),
            "security": (min(claim_coverage / 5, 1.0), f"{claim_coverage}/5 claim areas covered"),
            **{k: v for k, v in heuristic_categories(task, work, entry["checks"]).items()
               if k in ("instruction", "testing", "maintainability")},
        }
    elif task in ("T1", "T2", "T7"):
        entry["needs_judge"] = True
        structural = structural_checks(task, work)
        entry["checks"] = structural
        entry["categories"] = {k: v for k, v in heuristic_categories(task, work, structural).items()
                               if k in ("instruction", "testing", "maintainability")}

    if task not in ("T8",) and entry["checks"]:
        entry["categories"] = {**category_scores(task, entry["checks"], work),
                               **{k: v for k, v in entry["categories"].items() if k not in (
                                   "functional", "security", "instruction", "testing",
                                   "maintainability")}}
        if task in ("T3", "T5", "T4", "T6"):
            heur = heuristic_categories(task, work, entry["checks"])
            entry["categories"]["instruction"] = heur["instruction"]
            entry["categories"]["testing"] = heur["testing"]
            entry["categories"]["maintainability"] = heur["maintainability"]
    return entry


SECTIONS = {
    "T1": ["functional requirement", "nonfunctional", "ingestion", "connector", "retrieval",
           "classification", "tenant isolation", "audit", "monitoring", "approval",
           "testing", "acceptance", "deployment", "rollback", "work package", "dependenc"],
    "T2": ["scope", "state transition", "save", "cancel", "stale", "authoriz", "audit",
           "regression test", "migration", "acceptance", "unchanged", "line"],
    "T7": ["blocking", "non-blocking", "severity", "severity", "evidence", "remediation",
           "uncertainty", "merge recommendation", "file", "line"],
}


def structural_checks(task: str, work: pathlib.Path) -> list[dict]:
    """Presence of the required sections/references, from the deliverable text."""
    text = ""
    for p in work.iterdir():
        if p.is_file() and p.suffix == ".md" and p.name != "BRIEF.md":
            text += "\n" + p.read_text(errors="replace")
    low = text.lower()
    checks = []
    for i, needle in enumerate(SECTIONS[task], start=1):
        checks.append({"id": f"D{i:02d}", "group": "instruction", "passed": needle in low,
                       "detail": f"section/reference {needle!r} {'present' if needle in low else 'MISSING'}"})
    if task in ("T2", "T7"):
        refs = set(re.findall(r"(?:^|\s)([\w./-]+\.(?:py|js|html|sql|json|diff))(?::(\d+))?", text))
        files = {r[0] for r in refs}
        real = [f for f in files if (work / f).exists() or (work / "src" / f).exists()]
        checks.append({"id": "D90", "group": "functional", "passed": len(real) >= 2,
                       "detail": f"{len(real)} cited files exist in the tree ({sorted(real)[:4]})"})
    checks.append({"id": "D91", "group": "functional", "passed": len(text) > 1200,
                   "detail": f"deliverable length {len(text)} chars"})
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="")
    ap.add_argument("--runs", default=str(BENCH / "runs.jsonl"))
    args = ap.parse_args()
    runs = pathlib.Path(args.runs)
    records = []
    for line in runs.read_text().splitlines() if runs.exists() else []:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("status") in ("started", "dry-run"):
            continue
        if args.task and rec.get("task") != args.task:
            continue
        records.append(rec)
    (GRADING).mkdir(exist_ok=True)
    (QUEUE).mkdir(exist_ok=True)
    # keep only the last record per (task, candidate): a retried trial supersedes its attempt
    latest: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for rec in records:
        key = (rec.get("task", ""), (rec.get("workdir") or "").rstrip("/").split("/")[-1])
        if key not in latest:
            order.append(key)
        latest[key] = rec
    summary = []
    for key in order:
        rec = latest[key]
        entry = grade_trial(rec)
        out = GRADING / entry["task"] / f"{entry['label']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(entry, indent=2))
        if entry.get("needs_judge"):
            blob = ""
            for p in pathlib.Path(entry["workdir"]).iterdir():
                if p.is_file() and p.suffix == ".md" and p.name != "BRIEF.md":
                    blob += f"\n\n### {p.name}\n" + p.read_text(errors="replace")
            (QUEUE / f"{entry['task']}__{entry['label']}.txt").write_text(blob[:40000])
        passed = sum(1 for c in entry["checks"] if c.get("passed"))
        summary.append(f"{entry['task']:3} {entry['label']:20} checks {passed}/"
                       f"{len(entry['checks'])} categories={ {k: round(v[0], 2) for k, v in entry['categories'].items()} }")
    print("\n".join(summary) if summary else "(nothing graded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
