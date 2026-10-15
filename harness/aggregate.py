#!/usr/bin/env python3
"""Aggregate trial records + grading into scores.csv and summary.json.

    python3 harness/aggregate.py

Weights (documented maximums): functional 35, security 25, instruction 15, testing 10,
maintainability 10, efficiency 5. A category the task could not exercise is redistributed
proportionally across the categories that were scored, and the fact is recorded.

Critical-failure overrides are applied as the assignment defines them: permitting an
unauthorized cross-tenant operation, retaining a serious privilege-escalation path, weakening
a mandatory gate to get a green result, fabricating execution evidence, or claiming success
for behaviour that demonstrably fails.
"""
from __future__ import annotations

import csv
import json
import pathlib

BENCH = pathlib.Path(__file__).resolve().parent.parent
WEIGHTS = {"functional": 35, "security": 25, "instruction": 15, "testing": 10,
           "maintainability": 10, "efficiency": 5}
LABELS = {"haiku-5.5": "Claude Haiku 5.5", "gpt-6-luna": "GPT-6 Luna",
          "deepseek-v4.1-flash": "DeepSeek V4.1 Flash"}
TASK_GROUPS = {"T1": "planning", "T2": "framing", "T3": "backend", "T4": "frontend",
               "T5": "security", "T6": "ci", "T7": "review", "T8": "testing"}


def load_runs() -> dict[tuple[str, str], dict]:
    runs = {}
    path = BENCH / "runs.jsonl"
    if not path.exists():
        return runs
    for line in path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        label = (rec.get("workdir") or "").rstrip("/").split("/")[-1]
        if not label:
            continue
        key = (rec["task"], label)
        if rec.get("status") in ("started", "dry-run"):
            continue
        runs[key] = rec
    return runs


def load_grading() -> dict[tuple[str, str], dict]:
    out = {}
    for path in (BENCH / "grading").glob("T*/*.json"):
        data = json.loads(path.read_text())
        out[(data["task"], data["label"])] = data
    return out


def load_judge() -> dict[tuple[str, str], dict]:
    out = {}
    for path in (BENCH / "judge_results").glob("*.json"):
        if path.name.endswith(".usage.json"):
            continue
        data = json.loads(path.read_text())
        if data.get("_task") and data.get("_label"):
            out[(data["_task"], data["_label"])] = data
    return out


def critical_failures(task: str, entry: dict, judge: dict) -> list[str]:
    fails = []
    checks = {c.get("id"): c for c in entry.get("checks", [])}
    if task in ("T3", "T5"):
        for cid, what in (("A03", "a cross-tenant read is still possible"),
                          ("A04", "a cross-tenant revocation is still possible"),
                          ("A10", "an unknown role still fails open"),
                          ("A12", "a caller-supplied tenant id still moves a report")):
            if cid in checks and not checks[cid].get("passed"):
                fails.append(what)
    if task == "T4":
        if "S06" in checks and not checks["S06"].get("passed"):
            fails.append("a failed save can still be presented as a success")
        if "S05" in checks and not checks["S05"].get("passed"):
            fails.append("duplicate submissions can reach the API")
    if task == "T6":
        if "G2" in checks and not checks["G2"].get("passed"):
            fails.append("a failing test does not reach the release gate")
        if "G6" in checks and not checks["G6"].get("passed"):
            fails.append("a mandatory test or assertion was removed or weakened")

    for item in (judge or {}).get("critical_failures") or []:
        fails.append(f"evaluator: {item}")
    return fails


ADJUDICATIONS = {
    ("T4", "gpt-6-luna"): (
        "S04 failed on the frozen DOM contract: the confirmation control carries "
        "data-confirm=\"no\" before confirming instead of \"yes\". An independent probe "
        "(task-evidence/t4-luna-confirm-probe.txt) shows the behaviour is correct: applying an "
        "admin change without confirming writes nothing, and confirming then applying writes "
        "exactly one admin change. Contract miss, not a privilege-escalation miss."),
    ("T8", "gpt-6-luna"): (
        "Two assertions encode policy the task never fixed (a save_batch status string of "
        "\"failed\", and refusal of an owning analyst revoking). The suite is defect-sensitive; "
        "it is the second half of the two-sided check that fails."),
    ("T8", "deepseek-v4.1-flash"): (
        "Two assertions encode policy the task never fixed (revoked reports must remain in the "
        "listing, and only an admin may revoke). Defect-sensitive suite; fails the pass-on-correct "
        "half only."),
    ("T8", "claude-haiku-5-5"): (
        "Fully claim-validating suite: detects the seeded defects and passes on a correct "
        "implementation. It also caught two real bugs in the benchmark's own reference "
        "implementation (task-evidence/t8-reference-defects.txt)."),
}


def trial_score(entry: dict, judge: dict) -> dict:
    scores: dict[str, float] = {}
    for cat, value in (entry.get("categories") or {}).items():
        if cat in WEIGHTS and isinstance(value, (list, tuple)) and value:
            raw = value[0]
            scores[cat] = raw * 100 if raw <= 1.0 else raw
    if judge:
        for cat in ("functional", "security", "instruction", "maintainability", "testing",
                    "efficiency"):
            if isinstance(judge.get(cat), (int, float)):
                scores[cat] = float(judge[cat])
    if not scores:
        return {"overall": None, "categories": {}, "redistributed": []}
    # redistribute the weight of categories that were never scored
    missing = [c for c in WEIGHTS if c not in scores]
    weight_sum = sum(WEIGHTS[c] for c in scores)
    overall = sum(scores[c] * WEIGHTS[c] for c in scores) / weight_sum
    if "efficiency" not in scores:
        pass
    return {"overall": round(overall, 1), "categories": {k: round(v, 1) for k, v in scores.items()},
            "redistributed": missing}


def efficiency_scores(rows: list[dict]) -> None:
    """Relative efficiency within each task: time and metered cost, best = 100."""
    by_task: dict[str, list[dict]] = {}
    for row in rows:
        if row["overall"] is None or row.get("metered_usd") is None:
            continue
        by_task.setdefault(row["task"], []).append(row)
    for task, group in by_task.items():
        times = [r["elapsed_s"] for r in group if r.get("elapsed_s")]
        costs = [r["metered_usd"] for r in group if r.get("metered_usd")]
        if not times or not costs:
            continue
        best_t, best_c = min(times), min(costs)
        for row in group:
            t = row.get("elapsed_s") or best_t
            c = row.get("metered_usd") or best_c
            t_score = 100 * best_t / t if t else 0
            c_score = 100 * best_c / c if c else 0
            row["efficiency_relative"] = round(0.5 * t_score + 0.5 * c_score, 1)


def main() -> int:
    runs = load_runs()
    grading = load_grading()
    judge = load_judge()
    rows = []
    for (task, label), rec in sorted(runs.items()):
        entry = grading.get((task, label), {})
        judged = judge.get((task, label), {})
        score = trial_score(entry, judged) if entry else {"overall": None, "categories": {},
                                                          "redistributed": []}
        fails = critical_failures(task, entry, judged)
        usage = rec.get("usage") or {}
        rows.append({
            "task": task, "task_area": TASK_GROUPS.get(task), "label": label,
            "candidate": LABELS.get(label, label),
            "status": rec.get("status"),
            "elapsed_s": rec.get("elapsed_s"),
            "metered_usd": rec.get("metered_equivalents_usd"),
            "attempt": rec.get("attempt", 1),
            "substituted": rec.get("substituted"),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cache_read_tokens": usage.get("cache_read_tokens"),
            "cache_write_tokens": usage.get("cache_write_tokens"),
            "api_calls": usage.get("api_calls"),
            "overall": None if fails and "critical" else score["overall"],
            "raw_overall": score["overall"],
            "categories": score["categories"],
            "redistributed": score["redistributed"],
            "critical_failures": fails,
            "adjudications": ([ADJUDICATIONS[(task, label)]] if (task, label) in ADJUDICATIONS else []),
            "checks_passed": sum(1 for c in entry.get("checks", []) if c.get("passed")),
            "checks_total": len(entry.get("checks", [])),
            "files_touched": len(rec.get("files_touched") or []),
            "deliverables": rec.get("deliverables_present") or [],
        })
    efficiency_scores(rows)

    out = BENCH / "grading" / "summary.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rows, indent=2))

    csv_path = BENCH / "scores.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["task", "task_area", "candidate", "label", "status", "attempt",
                         "overall_score", "raw_score_before_overrides", "critical_failures", "adjudications",
                         "checks_passed", "checks_total", "functional", "security",
                         "instruction", "testing", "maintainability", "efficiency",
                         "elapsed_s", "metered_equiv_usd", "input_tokens", "output_tokens",
                         "cache_read_tokens", "cache_write_tokens", "api_calls",
                         "files_touched"])
        for row in sorted(rows, key=lambda r: (r["task"], r["label"])):
            cats = row["categories"]
            writer.writerow([
                row["task"], row["task_area"], row["candidate"], row["label"], row["status"],
                row["attempt"], row["overall"], row["raw_overall"],
                "; ".join(row["critical_failures"]), "; ".join(row.get("adjudications") or []),
                row["checks_passed"], row["checks_total"],
                cats.get("functional"), cats.get("security"), cats.get("instruction"),
                cats.get("testing"), cats.get("maintainability"), cats.get("efficiency"),
                row["elapsed_s"], row["metered_usd"], row["input_tokens"], row["output_tokens"],
                row["cache_read_tokens"], row["cache_write_tokens"], row["api_calls"],
                row["files_touched"],
            ])
    print(f"wrote {csv_path} and {out} ({len(rows)} trials)")
    for row in sorted(rows, key=lambda r: (r["task"], r["label"])):
        print(f"{row['task']:3} {row['candidate']:18} overall={row['overall']} "
              f"({row['checks_passed']}/{row['checks_total']} checks) "
              f"crit={len(row['critical_failures'])} ${row['metered_usd']} {row['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
