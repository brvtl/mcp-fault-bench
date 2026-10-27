"""Bundle the current scoreboard and event stream into a static replay directory."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from bench.arena import RESULTS, ROOT
from web.server import _jsonl

DIST = ROOT / "dist"


def main() -> None:
    """Write the page and JSON data files needed by a static replay."""
    DIST.mkdir(exist_ok=True)
    shutil.copy(ROOT / "web" / "index.html", DIST / "index.html")
    runs = []
    for row in _jsonl(RESULTS / "runs.jsonl"):
        row["events"] = []
        artifact_dir = ROOT / row.get("artifact_dir", "")
        if not artifact_dir.resolve().is_relative_to((RESULTS / "runs").resolve()):
            continue
        for log in artifact_dir.glob("*-proxy.jsonl"):
            row["events"].extend(_jsonl(log))
        runs.append(row)
    try:
        summary = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        summary = {}
    (DIST / "runs.json").write_text(json.dumps(runs), encoding="utf-8")
    (DIST / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    page = DIST / "index.html"
    html = page.read_text(encoding="utf-8").replace('fetch(`${endpoint}?t=${Date.now()}`)',
                                                        'fetch(`${endpoint.replace("/api/runs", "runs.json").replace("/api/summary", "summary.json")}?t=${Date.now()}`)')
    page.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
