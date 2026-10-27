"""Recompute the call-derived fields of every row in results/runs.jsonl from its stored agent output.

The output is parsed by the row's adapter (rows without an `adapter` field are claude-code: `claude.jsonl`).

    python scripts/rescore_calls.py [--runs results/runs.jsonl]

Updates retries (same tool + same arguments issued after that call's error result came back), retried_tools,
same_args_repeats, repeated_tools and the target_* post-error fields. Every other field is left as recorded.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.adapters import get_adapter, row_adapter  # noqa: E402
from bench.arena import agent_fallbacks, retry_counts, target_behaviour  # noqa: E402


def rescore(row: dict, root: Path = ROOT, fallbacks: dict | None = None) -> dict:
    calls = get_adapter(row_adapter(row)).parse(root / row["artifact_dir"])["calls"]
    repeats = retry_counts([call for call in calls if call["name"].startswith("mcp__")])
    return {**row, **repeats, **target_behaviour(calls, row.get("target_tool"), fallbacks)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, default=ROOT / "results" / "runs.jsonl")
    args = parser.parse_args()
    fallbacks = agent_fallbacks()
    rows = [json.loads(line) for line in args.runs.read_text().splitlines() if line.strip()]
    updated = [rescore(row, fallbacks=fallbacks) for row in rows]
    changed = sum(old.get("retries") != new["retries"] for old, new in zip(rows, updated))
    args.runs.write_text("".join(json.dumps(row) + "\n" for row in updated), encoding="utf-8")
    print(f"rescored {len(updated)} rows; retries changed on {changed}")


if __name__ == "__main__":
    main()
