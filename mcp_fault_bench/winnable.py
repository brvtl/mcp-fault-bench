"""Winnable-draw rep extension: pick extra reps by their first drawn entry, from seed strings alone."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .proxy import first_draw, load_schedule


def rule_text(schedule_path: str, seed: Any, start: int, per_task: int, exclude: list[str]) -> str:
    return (f"For each task, walk reps {start}, {start + 1}, ... with seed string '{seed}:<task>:<rep>' and keep the "
            f"first {per_task} reps whose first drawn entry under {schedule_path} (draw_index 0, computed by "
            f"chaosmonkey.proxy.first_draw) is not in {sorted(exclude)}. The rule depends only on seed strings and "
            "the profile weights, never on a model or a run outcome.")


def winnable_reps(schedule: dict[str, Any], seed: Any, tasks: list[str], start: int, per_task: int,
                  exclude: list[str], limit: int = 100_000) -> tuple[dict[str, list[int]], dict[str, list[list[Any]]]]:
    """(kept reps per task, skipped [rep, label] pairs per task)."""
    kept: dict[str, list[int]] = {}
    skipped: dict[str, list[list[Any]]] = {}
    excluded = set(exclude)
    for task in tasks:
        kept[task], skipped[task] = [], []
        rep = start
        while len(kept[task]) < per_task:
            if rep - start >= limit:
                raise ValueError(f"no {per_task} winnable reps for {task} within {limit} reps")
            label = first_draw(schedule, f"{seed}:{task}:{rep}")
            if label in excluded:
                skipped[task].append([rep, label])
            else:
                kept[task].append(rep)
            rep += 1
    return kept, skipped


def write_winnable_reps(schedule_path: str, seed: Any, start: int, per_task: int, exclude: list[str],
                        task_file: str, tasks: list[str] | None, output: str) -> dict[str, Any]:
    """Compute the rep file and write it to ``output``."""
    task_ids = tasks or [task["id"] for task in yaml.safe_load(Path(task_file).read_text(encoding="utf-8"))["tasks"]]
    kept, skipped = winnable_reps(load_schedule(schedule_path), seed, task_ids, start, per_task, exclude)
    document: dict[str, Any] = {**kept, "rule": rule_text(schedule_path, seed, start, per_task, exclude),
                                "skipped": skipped}
    Path(output).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document


def load_rep_file(path: str) -> dict[str, list[int]]:
    """{task: [reps]} from a winnable_reps.json (metadata keys ignored)."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    return {task: [int(rep) for rep in reps] for task, reps in document.items()
            if task not in ("rule", "skipped") and isinstance(reps, list)}
