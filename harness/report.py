#!/usr/bin/env python3
"""Assemble the BENCH-MODEL-001 dossier from trial records + grading + judging.

    python3 harness/report.py

Writes into dossier/:
  executive-comparison.md   per-candidate, per-task scores and the headline metrics
  decision-matrix.md        role suitability, with qualification levels and confidence
  proposed-delegation.yaml  a PROPOSED routing (every entry explicitly inactive)
  lessons-learned.md        strengths/weaknesses derived from the actual check failures
  first-attempts.md         first-attempt vs final outcome per trial, retries separated

Nothing here invents a number: every figure comes from runs.jsonl, grading/summary.json or
judge_results/. Ties within 5 points are reported as provisional ties.
"""
from __future__ import annotations

import json
import pathlib
from collections import Counter, defaultdict

BENCH = pathlib.Path(__file__).resolve().parent.parent
DOSSIER = BENCH / "dossier"
TASKS = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]
TASK_NAME = {"T1": "Requirements + planning", "T2": "Work-package framing", "T3": "Backend feature",
             "T4": "Frontend/admin safety", "T5": "Security + isolation", "T6": "CI diagnosis + repair",
             "T7": "Independent code review", "T8": "Test design + acceptance"}
LABELS = {"haiku-5.5": "Claude Haiku 5.5", "gpt-6-luna": "GPT-6 Luna",
          "deepseek-v4.1-flash": "DeepSeek V4.1 Flash"}
ROLES = [
    ("1. Requirements analysis", ["T1"], ["functional", "security", "instruction"]),
    ("2. Architecture and work-package framing", ["T2"], ["functional", "maintainability"]),
    ("3. Backend implementation", ["T3"], ["functional", "security", "testing"]),
    ("4. Frontend / UI implementation", ["T4"], ["functional", "security"]),
    ("5. Security-sensitive implementation", ["T5"], ["security", "functional"]),
    ("6. CI failure diagnosis and repair", ["T6"], ["functional", "instruction"]),
    ("7. Independent code review", ["T7"], ["functional", "security"]),
    ("8. Testing and acceptance engineering", ["T8"], ["functional", "testing"]),
    ("9. Documentation and handoff drafting", ["T1", "T2"], ["instruction", "efficiency"]),
]


def load() -> tuple[list[dict], dict, list[dict]]:
    summary_path = BENCH / "grading" / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else []
    runs = defaultdict(list)
    runs_path = BENCH / "runs.jsonl"
    for line in runs_path.read_text().splitlines() if runs_path.exists() else []:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        label = (rec.get("workdir") or "").rstrip("/").split("/")[-1]
        if label:
            runs[(rec["task"], label)].append(rec)
    grading = {}
    for path in (BENCH / "grading").glob("T*/*.json"):
        data = json.loads(path.read_text())
        grading[(data["task"], data["label"])] = data
    return summary, runs, grading


def qualify(score: float | None, criticals: list[str], evidence_note: str) -> tuple[str, str]:
    if score is None:
        return "Not yet qualified", "no usable trial result"
    if criticals:
        return "Not yet qualified", f"unresolved critical failure: {criticals[0]}"
    if score >= 85:
        return "Autonomous candidate", evidence_note
    if score >= 70:
        return "Supervised candidate", evidence_note
    return "Not yet qualified", "role score below 70"


def main() -> int:
    summary, runs, grading = load()
    DOSSIER.mkdir(exist_ok=True)
    by = {(r["task"], r["label"]): r for r in summary}

    # ---- executive comparison -------------------------------------------------------
    lines = ["# Executive comparison", "",
             "Scores are out of 100 on the documented weights (functional 35, security 25, "
             "instruction 15, testing 10, maintainability 10, efficiency 5). `n/a` means the trial "
             "had not produced a gradable result. A trial with a critical failure keeps its raw "
             "score but is excluded from qualification.", "",
             "| Task | Area | " + " | ".join(LABELS.values()) + " |",
             "|---|---|" + "---|" * len(LABELS)]
    for task in TASKS:
        cells = []
        for label in LABELS:
            row = by.get((task, label))
            if not row or row.get("overall") is None:
                cells.append("n/a" if not row else f"{row['raw_overall']} (critical {len(row['critical_failures'])})")
            else:
                mark = "*" if row.get("critical_failures") else ""
                cells.append(f"{row['overall']}{mark}")
        lines.append(f"| {task} | {TASK_NAME[task]} | " + " | ".join(cells) + " |")
    lines += ["", "`*` = critical failure recorded for that trial.", "",
              "## Headline metrics", "",
              "| Candidate | Overall (mean of graded tasks) | Tasks graded | First-attempt success | "
              "Final success | Critical failures | Total time | Metered-equivalent cost |",
              "|---|---|---|---|---|---|---|---|"]
    for label in LABELS:
        rows = [r for r in summary if r["label"] == label]
        graded = [r["overall"] for r in rows if r.get("overall") is not None]
        mean = round(sum(graded) / len(graded), 1) if graded else None
        first_ok = 0
        for (task, lab), recs in runs.items():
            if lab != label:
                continue
            first = min(recs, key=lambda r: r.get("started_utc") or "")
            if first.get("status") == "completed" and not first.get("effort_note"):
                first_ok += 1
        final_ok = len(graded)
        crit = sum(len(r.get("critical_failures") or []) for r in rows)
        total_t = round(sum(r.get("elapsed_s") or 0 for r in rows), 1)
        cost = round(sum(r.get("metered_usd") or 0 for r in rows), 4)
        lines.append(f"| {LABELS[label]} | {mean} | {len(graded)} | {first_ok} | {final_ok} | {crit} | "
                     f"{total_t}s | ${cost} |")
    (DOSSIER / "executive-comparison.md").write_text("\n".join(lines) + "\n")

    # ---- role suitability -----------------------------------------------------------
    matrix = ["# Role suitability matrix", "",
              "Levels follow the assignment: **Autonomous candidate** (>= 85, no critical failures, "
              "objective acceptance satisfied), **Supervised candidate** (70-84, no critical "
              "failures), **Not yet qualified** (< 70 or an unresolved critical failure).", ""]
    delegations = {}
    for role, tasks, cats in ROLES:
        scores: dict[str, float | None] = {}
        notes: dict[str, str] = {}
        crits: dict[str, list[str]] = {}
        for label in LABELS:
            vals = []
            criticals = []
            for task in tasks:
                row = by.get((task, label))
                if not row:
                    continue
                criticals += row.get("critical_failures") or []
                got = [row["categories"].get(c) for c in cats if row["categories"].get(c) is not None]
                if got:
                    vals.append(sum(got) / len(got))
            scores[label] = round(sum(vals) / len(vals), 1) if vals else None
            crits[label] = criticals
            notes[label] = (f"{len(vals)} task(s) scored" if vals else "no gradable trial")
        ranked = sorted((s for s in scores.items() if s[1] is not None), key=lambda kv: -kv[1])
        best = ranked[0] if ranked else (None, None)
        second = ranked[1] if len(ranked) > 1 else (None, None)
        tie = bool(best[1] is not None and second[1] is not None and best[1] - second[1] <= 5)
        for label in LABELS:
            level, why = qualify(scores[label], crits[label], notes[label])
            delegations[label] = delegations.get(label, [])
            if level != "Not yet qualified":
                delegations[label].append(f"{role} ({level})")
        matrix.append(f"## {role}")
        matrix.append("")
        matrix.append("| Candidate | Score | Level | Evidence | Must not do unsupervised |")
        matrix.append("|---|---|---|---|---|")
        for label in LABELS:
            level, why = qualify(scores[label], crits[label], notes[label])
            forbidden = {
                "Autonomous candidate": "merges, releases, production changes (retained by policy)",
                "Supervised candidate": "unreviewed security-sensitive or gate-affecting changes",
                "Not yet qualified": "the role itself",
            }[level]
            matrix.append(f"| {LABELS[label]} | {scores[label]} | {level} | {why} | {forbidden} |")
        if best[0]:
            label = LABELS[best[0]]
            if tie:
                matrix.append(f"\n**Provisional tie** between {label} and {LABELS[second[0]]} "
                              f"({best[1]} vs {second[1]}, within 5 points): a single observation per "
                              "task cannot separate them.")
            else:
                matrix.append(f"\n**Preferred:** {label}. **Secondary:** "
                              f"{LABELS[second[0]] if second[0] else 'none scored'}.")
        else:
            matrix.append("\n**No candidate has a gradable result for this role yet.**")
        matrix.append("")
    matrix.append("No claim is made here that any tested model outperforms GLM-5.3 Flash: it "
                  "appears in this benchmark only as the qualitative evaluator, and no direct "
                  "comparison was run.")
    (DOSSIER / "decision-matrix.md").write_text("\n".join(matrix) + "\n")

    # ---- proposed delegation (explicitly inactive) ----------------------------------
    yaml = ["# PROPOSED delegation map for BENCH-MODEL-001.", "#",
            "# STATUS: INACTIVE. Nothing here has been applied. No routing configuration was",
            "# changed by this benchmark; the user and Sol decide whether any of it is adopted.",
            "active: false",
            "generated_from: dossier/decision-matrix.md",
            "proposed_roles:"]
    for role, _tasks, _cats in ROLES:
        cand = [c for c, roles in delegations.items() if any(role in r for r in roles)]
        yaml.append(f"  - role: {role!r}")
        yaml.append(f"    qualified: {[LABELS[c] for c in cand] or []}")
    yaml += ["", "# Not proposed: any change to the current supervisor/implementer/reviewer split,",
             "# any production model assignment, and any merge, release or deploy authority.",
             "# GLM-5.3 Flash remains in its current role pending a separate direct comparison."]
    (DOSSIER / "proposed-delegation.yaml").write_text("\n".join(yaml) + "\n")

    # ---- first attempts -------------------------------------------------------------
    fa = ["# First attempt versus final outcome", "",
          "A trial that was lost to a provider stall or a rejected substitution is retried once with "
          "a fresh session; the first attempt is preserved here and never scored as a zero.", "",
          "| Task | Candidate | First attempt | Retries | Final status | Final score | Note |",
          "|---|---|---|---|---|---|---|"]
    for (task, label) in sorted(runs):
        recs = sorted(runs[(task, label)], key=lambda r: r.get("started_utc") or "")
        first = recs[0]
        last = recs[-1]
        row = by.get((task, label), {})
        note = first.get("retry_reason") or first.get("interrupted") or ""
        fa.append(f"| {task} | {LABELS.get(label, label)} | {first.get('status')} | {len(recs) - 1} | "
                  f"{last.get('status')} | {row.get('overall')} | {note} |")
    (DOSSIER / "first-attempts.md").write_text("\n".join(fa) + "\n")

    # ---- lessons learned from actual failures ---------------------------------------
    failures: dict[str, Counter] = defaultdict(Counter)
    for (task, label), data in grading.items():
        for check in data.get("checks", []):
            if not check.get("passed") and not check.get("not_applicable"):
                failures[label][f"{task}:{check.get('id')} {check.get('group')}"] += 1
    ls = ["# Lessons learned (from the failures that actually occurred)", ""]
    for label in LABELS:
        counter = failures.get(label) or Counter()
        ls.append(f"## {LABELS[label]}")
        ls.append("")
        if not counter:
            ls.append("No failing checks recorded yet in the graded set.")
        else:
            ls.append("Failing checks observed: " + ", ".join(f"`{k}`" for k in sorted(counter)))
        rows = [r for r in summary if r["label"] == label]
        crit = [c for r in rows for c in (r.get("critical_failures") or [])]
        if crit:
            ls.append("")
            ls.append("Critical failures: " + "; ".join(sorted(set(crit))))
        ls.append("")
    ls += ["## Reading these", "",
           "The counter above is the honest summary: it lists the checks each candidate actually "
           "failed, per task. A model with no failing checks in the graded set has not been shown "
           "to be reliable beyond the tasks it completed; see limitations.md section 6."]
    (DOSSIER / "lessons-learned.md").write_text("\n".join(ls) + "\n")

    print("dossier written:", ", ".join(sorted(p.name for p in DOSSIER.iterdir())))
    print(f"trials in summary: {len(summary)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
