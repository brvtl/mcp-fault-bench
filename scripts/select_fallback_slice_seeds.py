"""Pick extension seeds for the fallback slice from seed strings, profiles and clean-run records alone.

    python scripts/select_fallback_slice_seeds.py [--start 11] [--count 20] [--output bench/fallback_slice_reps.json]
                                                  [--check]

A (task, rep) is eligible when, for seed string '42:<task>:<rep>', the first drawn entry under
profiles/paper_opp_scoped.yaml is OP4/permanent, the one-tool target (bench.arena.pick_target) has a fallback in
profiles/shim.yaml, and the target is on-path: every clean run with rep 1-10 of that task called it (proxy logs).
Reps are walked rep-major from --start, tasks in bench/tasks.yaml order, keeping the first --count eligible pairs.
No chaos run outcome is read. --check also applies the rule to reps 1-10 and requires the original 10-seed slice.
The output is a rep file for `python -m mcp_fault_bench arena --rep-file`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.arena import HEADLINE_REPS, UNWINNABLE, pick_target  # noqa: E402
from mcp_fault_bench.proxy import first_draw, load_schedule  # noqa: E402

SEED = 42
SCHEDULE = "profiles/paper_opp_scoped.yaml"
SHIM = "profiles/shim.yaml"
TASKS = "bench/tasks.yaml"
RUNS = "results/runs.jsonl"
# The 10-seed slice of docs/preregistration-shim.md (one-tool condition, reps 1-10).
ORIGINAL = {"note_summary": [1, 2, 9], "budget_order": [2, 10], "cross_server_total": [4, 5, 6],
            "restock_cost": [5, 9]}


def on_path_tools(rows: list[dict[str, Any]], root: Path = ROOT) -> dict[str, set[str]]:
    """Per task: tools called (proxy log field "tool") in every clean run with rep 1-10."""
    seen: dict[str, set[str]] = {}
    for row in rows:
        if row.get("condition") != "clean" or not 1 <= int(row["rep"]) <= HEADLINE_REPS:
            continue
        tools = set()
        for log in sorted((root / row["artifact_dir"]).glob("*-proxy.jsonl")):
            events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
            tools.update(event["tool"] for event in events if event.get("tool"))
        seen[row["task"]] = seen[row["task"]] & tools if row["task"] in seen else tools
    return seen


def eligible(schedule: dict[str, Any], fallbacks: dict[str, Any], on_path: dict[str, set[str]],
             task: dict[str, Any], rep: int) -> tuple[bool, str | None, str | None]:
    """(eligible, target, skip reason); the reason is set only for seed-eligible but off-path pairs."""
    target = pick_target(SEED, task, rep)
    if first_draw(schedule, f"{SEED}:{task['id']}:{rep}") != UNWINNABLE or target not in fallbacks:
        return False, target, None
    if target not in on_path.get(task["id"], set()):
        return False, target, f"off-path target {target}"
    return True, target, None


def select(tasks: list[dict[str, Any]], schedule: dict[str, Any], fallbacks: dict[str, Any],
           on_path: dict[str, set[str]], start: int, count: int | None, stop: int | None = None,
           limit: int = 100_000) -> tuple[list[tuple[str, int, str]], dict[str, list[list[Any]]]]:
    """Walk reps from ``start`` (rep-major, task order) until ``count`` eligible pairs or past rep ``stop``."""
    kept: list[tuple[str, int, str]] = []
    skipped: dict[str, list[list[Any]]] = {}
    rep = start
    while (count is None or len(kept) < count) and (stop is None or rep <= stop):
        if rep - start >= limit:
            raise ValueError(f"no {count} eligible pairs within {limit} reps")
        for task in tasks:
            if count is not None and len(kept) >= count:
                break
            ok, target, reason = eligible(schedule, fallbacks, on_path, task, rep)
            if ok:
                kept.append((task["id"], rep, target))
            elif reason:
                skipped.setdefault(task["id"], []).append([rep, reason])
        rep += 1
    return kept, skipped


def as_reps(pairs: list[tuple[str, int, str]]) -> dict[str, list[int]]:
    reps: dict[str, list[int]] = {}
    for task, rep, _ in pairs:
        reps.setdefault(task, []).append(rep)
    return reps


def rule_text(start: int, count: int) -> str:
    return (f"Walk reps {start}, {start + 1}, ... (rep-major, tasks in {TASKS} order) with seed string "
            f"'{SEED}:<task>:<rep>' and keep the first {count} (task, rep) pairs whose first drawn entry under "
            f"{SCHEDULE} (chaosmonkey.proxy.first_draw) is {UNWINNABLE}, whose one-tool target "
            f"(bench.arena.pick_target) has a fallback in {SHIM}, and whose target is on-path: it appears in the "
            f"proxy logs of every clean run with rep 1-{HEADLINE_REPS} of that task in {RUNS}. Applied to reps "
            f"1-{HEADLINE_REPS} the rule gives the original 10-seed slice. It depends only on seed strings, profiles "
            "and clean-run records, never on a chaos run outcome.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=int, default=HEADLINE_REPS + 1)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--output", default="bench/fallback_slice_reps.json")
    parser.add_argument("--check", action="store_true", help="also require the rule on reps 1-10 to give the original slice")
    args = parser.parse_args()

    tasks = yaml.safe_load((ROOT / TASKS).read_text(encoding="utf-8"))["tasks"]
    schedule = load_schedule(str(ROOT / SCHEDULE))
    fallbacks = yaml.safe_load((ROOT / SHIM).read_text(encoding="utf-8"))["fallbacks"]
    rows = [json.loads(line) for line in (ROOT / RUNS).read_text(encoding="utf-8").splitlines() if line.strip()]
    on_path = on_path_tools(rows)

    if args.check:
        pairs, skipped = select(tasks, schedule, fallbacks, on_path, 1, None, stop=HEADLINE_REPS)
        print(f"rule on reps 1-{HEADLINE_REPS}: {len(pairs)} pair(s)")
        for task, rep, target in pairs:
            print(f"  {task} {rep} {target}")
        print(f"  skipped: {json.dumps(skipped)}")
        if as_reps(pairs) != ORIGINAL:
            print(f"check failed: expected {ORIGINAL}", file=sys.stderr)
            return 1
        print("  matches the original 10-seed slice")

    pairs, skipped = select(tasks, schedule, fallbacks, on_path, args.start, args.count)
    print(f"selected {len(pairs)} pair(s) from rep {args.start}:")
    for task, rep, target in pairs:
        print(f"  {task} {rep} {target}")
    print(f"  skipped: {json.dumps(skipped)}")
    document: dict[str, Any] = {**as_reps(pairs), "rule": rule_text(args.start, args.count), "skipped": skipped}
    output = Path(args.output) if Path(args.output).is_absolute() else ROOT / args.output
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
