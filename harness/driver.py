#!/usr/bin/env python3
"""BENCH-MODEL-001 trial driver.

    python3 harness/driver.py --stage a            # T2, T4, T6 x 3 candidates
    python3 harness/driver.py --stage b            # T1, T3, T5, T7, T8 x 3
    python3 harness/driver.py --stage c            # T4, T6 repeats
    python3 harness/driver.py --only T6 --models gpt-6-luna

One trial = one fresh Hermes session pinned to one model, running the frozen brief in its own
copy of the fixture, in an isolated HERMES_HOME that has no fallback provider configured (so a
candidate can never be silently substituted). Every trial appends one record to runs.jsonl.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time

BENCH = pathlib.Path(__file__).resolve().parent.parent
HH = BENCH / "hermes-home"
RUNS = BENCH / "runs"
FIX = BENCH / "fixtures"
TASKS = BENCH / "tasks"
LOG = BENCH / "runs.jsonl"

# Candidate -> (requested model id, provider route).  See limitations.md: the shipped build's
# OpenCode Go wire table has no claude-* entry, so Haiku is reached through the equivalent
# explicitly declared anthropic-wire route to the same relay.
CANDIDATES: dict[str, dict[str, str]] = {
    "claude-haiku-5-5": {"provider": "go-anthropic", "label": "haiku-5.5"},
    "gpt-6-luna": {"provider": "opencode-go", "label": "gpt-6-luna"},
    "deepseek-v4.1-flash": {"provider": "opencode-go", "label": "deepseek-v4.1-flash"},
}

# OpenCode Go published rates, USD per 1M tokens (https://opencode.ai/docs/go/).
RATES = {
    "claude-haiku-5-5": {"low": (0.10, 0.50, 0.01, 0.125), "high": (0.50, 2.50, 0.05, 0.625),
                         "threshold": 100_000},
    "gpt-6-luna": {"low": (0.10, 0.50, 0.01, 0.125), "high": (0.20, 0.75, 0.02, 0.25),
                   "threshold": 272_000},
    "deepseek-v4.1-flash": {"low": (0.15, 0.60, 0.003, 0.0), "high": (0.30, 1.20, 0.006, 0.0),
                            "threshold": None},
}

TASK_FIXTURE = {
    "T1": None, "T2": "adminaccess", "T3": "reportcore_t3", "T4": "adminui",
    "T5": "reportcore_t5", "T6": "cifix", "T7": "review_diff", "T8": "reportcore_t8",
}

STAGES = {
    "a": ["T2", "T4", "T6"],
    "b": ["T1", "T3", "T5", "T7", "T8"],
    "c": ["T4", "T6"],
}

CEILING_USD = 1.50  # metered-equivalent consumption per candidate, benchmark budget


def deepseek_peak(now_utc: _dt.datetime) -> bool:
    if now_utc.weekday() >= 5:
        return False
    hour = now_utc.hour
    return (1 <= hour < 4) or (6 <= hour < 10)


def metered_cost(model: str, usage: dict, now_utc: _dt.datetime) -> tuple[float, str]:
    """Metered-equivalent USD from the published Go rate card, with a low/high tier bound."""
    rate = RATES.get(model)
    if not rate:
        return 0.0, "unknown model: no rate"
    if model == "deepseek-v4.1-flash":
        band = "high" if deepseek_peak(now_utc) else "low"
        price = rate[band]
        note = f"deepseek {'peak' if band == 'high' else 'off-peak'} rate"
        return _cost(price, usage), note
    low, high = rate["low"], rate["high"]
    prompt = (usage.get("input_tokens") or 0) + (usage.get("cache_read_tokens") or 0) \
        + (usage.get("cache_write_tokens") or 0)
    if prompt <= (rate["threshold"] or 0):
        return _cost(low, usage), "prompt under the long-context threshold"
    return _cost(high, usage), "prompt over the long-context threshold"


def _cost(price: tuple[float, float, float, float], usage: dict) -> float:
    inp, out, cread, cwrite = price
    return round(
        ((usage.get("input_tokens") or 0) * inp
         + (usage.get("output_tokens") or 0) * out
         + (usage.get("cache_read_tokens") or 0) * cread
         + (usage.get("cache_write_tokens") or 0) * cwrite) / 1_000_000,
        6,
    )


def tree_digest(root: pathlib.Path, skip_dirs=("__pycache__", ".git", "node_modules")) -> dict:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        try:
            rel = path.relative_to(root).as_posix()
            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        except OSError:
            continue
    return files


def prepare(tid: str, model: str, stage: str) -> pathlib.Path:
    label = CANDIDATES[model]["label"]
    work = RUNS / stage / tid / label
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / "BRIEF.md").write_text((TASKS / f"{tid}.md").read_text())
    fixture = TASK_FIXTURE[tid]
    if fixture:
        for item in (FIX / fixture).iterdir():
            dest = work / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
    if tid == "T1":
        shutil.copy2(TASKS / "FACTS.md", work / "FACTS.md")
    (work / ".bench-fixture-baseline.json").write_text(
        json.dumps(tree_digest(work), indent=1, sort_keys=True)
    )
    return work


def run_trial(tid: str, model: str, stage: str, timeout: float, dry: bool = False) -> dict:
    label = CANDIDATES[model]["label"]
    provider = CANDIDATES[model]["provider"]
    work = prepare(tid, model, stage)
    brief = (TASKS / f"{tid}.md").read_text()
    env = dict(os.environ)
    env["HERMES_HOME"] = str(HH)
    env.pop("OPENCODE_GO_BASE_URL", None)
    usage_path = work / "usage.json"
    cmd = ["hermes", "-z", brief, "-m", model, "--provider", provider,
           "--in", str(work), "--usage-file", str(usage_path), "--reasoning", "medium", "--yolo"]
    record = {"task": tid, "model": model, "requested_model": model, "provider_route": provider,
              "stage": stage, "workdir": str(work), "started_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
              "status": "started"}
    if dry:
        record["status"] = "dry-run"
        return record
    started = time.time()
    with (work / "stdout.txt").open("wb") as out, (work / "stderr.txt").open("wb") as err:
        proc = subprocess.Popen(cmd, cwd=str(work), env=env, stdout=out, stderr=err,
                                start_new_session=True)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:  # noqa: BLE001
                proc.kill()
            proc.wait(timeout=30)
            record["interrupted"] = "timeout"
    record["elapsed_s"] = round(time.time() - started, 1)
    record["exit_code"] = proc.returncode
    record["command"] = " ".join(cmd[:6] + ["<brief>"] + cmd[7:])
    usage = {}
    if usage_path.exists():
        try:
            usage = json.loads(usage_path.read_text())
        except ValueError:
            usage = {}
    record["usage"] = usage
    record["actual_model"] = usage.get("model")
    record["substituted"] = bool(usage.get("model")) and usage.get("model") != model
    now = _dt.datetime.now(_dt.timezone.utc)
    cost, note = metered_cost(model, usage, now)
    record["metered_equivalents_usd"] = cost
    record["cost_note"] = note
    record["cost_reported_by_hermes"] = usage.get("estimated_cost_usd")
    record["completed"] = usage.get("completed")
    record["status"] = "completed" if usage.get("completed") else ("failed" if proc.returncode else "unknown")
    baseline = json.loads((work / ".bench-fixture-baseline.json").read_text())
    after = tree_digest(work)
    changed = sorted(k for k, v in after.items() if baseline.get(k) != v)
    record["files_touched"] = changed
    record["deliverables_present"] = sorted(
        p.name for p in work.iterdir()
        if p.is_file() and p.suffix in (".md", ".png") and p.name != "BRIEF.md"
    )
    record["stdout_tail"] = (work / "stdout.txt").read_text(errors="replace")[-1500:]
    record["session_id"] = usage.get("session_id")
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="a", choices=sorted(STAGES))
    ap.add_argument("--only", default="")
    ap.add_argument("--models", default="")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tasks = [t.strip() for t in args.only.split(",") if t.strip()] or STAGES[args.stage]
    models = [m.strip() for m in args.models.split(",") if m.strip()] or list(CANDIDATES)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    spend = {m: 0.0 for m in models}
    if LOG.exists():
        for line in LOG.read_text().splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("model") in spend and rec.get("stage") == args.stage:
                spend[rec["model"]] += rec.get("metered_equivalents_usd") or 0.0

    total = 0
    for index, tid in enumerate(tasks):
        order = models[index % len(models):] + models[:index % len(models)]  # rotate execution order
        for model in order:
            if spend.get(model, 0.0) > CEILING_USD:
                print(f"SKIP {tid}/{model}: budget ceiling {CEILING_USD} reached "
                      f"({spend[model]:.4f} metered-equivalent)", flush=True)
                continue
            print(f"== {tid} / {model} ({CANDIDATES[model]['provider']}) starting", flush=True)
            rec = None
            for attempt in (1, 2):
                try:
                    rec = run_trial(tid, model, args.stage, args.timeout, dry=args.dry_run)
                except Exception as exc:  # noqa: BLE001
                    rec = {"task": tid, "model": model, "stage": args.stage,
                           "status": "driver_error", "error": f"{type(exc).__name__}: {exc}",
                           "workdir": str(RUNS / args.stage / tid / CANDIDATES[model]["label"])}
                interrupted = bool(rec.get("interrupted")) or rec.get("exit_code", 0) < 0 \
                    or not (rec.get("usage") or {})
                rec["attempt"] = attempt
                if not interrupted or attempt == 2 or args.dry_run:
                    break
                rec["status"] = "environmental_interruption"
                rec["retry_reason"] = "no usable result (stalled or killed); retrying once with a fresh session"
                print(f"== {tid} / {model} interrupted ({rec.get('interrupted') or rec.get('exit_code')}); "
                      f"retrying", flush=True)
            spend[rec["model"]] = spend.get(rec["model"], 0.0) + (rec.get("metered_equivalents_usd") or 0)
            rec["stage_spend_after"] = round(spend.get(rec["model"], 0.0), 6)
            with LOG.open("a") as fh:
                fh.write(json.dumps(rec) + "\n")
            total += 1
            print(f"== {tid} / {model} {rec.get('status')} "
                  f"elapsed={rec.get('elapsed_s')}s cost=${rec.get('metered_equivalents_usd')} "
                  f"files={len(rec.get('files_touched') or [])} "
                  f"subst={rec.get('substituted')}", flush=True)
    print(f"stage {args.stage}: {total} trials appended to {LOG}", flush=True)
    print("spend:", {k: round(v, 4) for k, v in spend.items()}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
