"""Serve the static dashboard and read-only arena JSON endpoints."""

from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = Path(__file__).resolve().parent
RUNS_ROOT = ROOT / "results" / "runs"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    """Load valid JSON object rows from a JSONL artifact."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


class Handler(SimpleHTTPRequestHandler):
    """Static page handler with small endpoints for runs, summaries, and logs."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/runs":
            self._send_json(self._load_runs())
            return
        if path == "/api/summary":
            summary_path = ROOT / "results" / "summary.json"
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                summary = {}
            self._send_json(summary)
            return
        if path.startswith("/api/log/"):
            self._send_log(path.removeprefix("/api/log/"))
            return
        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    def _load_runs(self) -> list[dict[str, Any]]:
        runs = []
        for row in _jsonl(ROOT / "results" / "runs.jsonl"):
            row["events"] = []
            artifact_dir = ROOT / row.get("artifact_dir", "")
            if not artifact_dir.resolve().is_relative_to(RUNS_ROOT.resolve()):
                continue
            for log_path in artifact_dir.glob("*-proxy.jsonl"):
                row["events"].extend(_jsonl(log_path))
            runs.append(row)
        return runs

    def _send_log(self, relative_path: str) -> None:
        target = (RUNS_ROOT / relative_path).resolve()
        if not target.is_relative_to(RUNS_ROOT.resolve()):
            self.send_error(403)
            return
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, value: Any) -> None:
        content = json.dumps(value).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def serve(port: int = 8787) -> None:
    """Run the local dashboard server until interrupted."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Serving MCP Fault Bench at http://127.0.0.1:{port}", flush=True)
    server.serve_forever()
