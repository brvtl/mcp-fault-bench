"""Scripted proxy sessions shared by the shim tests and the shim-off golden file.

tests/golden/shim_off.json was recorded from the proxy before the resilience shim existed (commit 81bb33d):

    .venv/bin/python -m tests.proxy_sessions > tests/golden/shim_off.json

Seeds are dev strings ("dev:<n>"), never arena seed strings.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VOLATILE = ("ts", "run_id", "latency")

INVENTORY_CALLS = [("get_price", {"sku": "SKU-731"}), ("get_price_v2", {"sku": "SKU-731"}),
                   ("search_products", {"category": "tea"}), ("get_stock", {"sku": "SKU-562"}),
                   ("place_order", {"sku": "SKU-562", "quantity": 1}), ("list_orders", {}),
                   ("get_product", {"sku": "SKU-916"}), ("get_price", {"sku": "SKU-916"})]
NOTES_CALLS = [("put_note", {"key": "a", "value": "alpha beta"}), ("get_note", {"key": "a"}),
               ("list_notes", {}), ("search_notes", {"query": "beta"}), ("get_note", {"key": "a"})]
RULES = {"seed": "dev:rules", "faults": [
    {"op": "error", "tools": ["get_price"], "persistence": "permanent", "activation_p": 1.0,
     "params": {"style": "tool_result", "message": "Access Denied to: get_price (service unavailable 503)"}},
    {"op": "wrong_type", "tools": ["get_price_v2"], "persistence": "transient", "activation_p": 1.0, "max_fires": 1},
    {"op": "random_value", "tools": ["get_stock"], "persistence": "transient", "activation_p": 1.0, "max_fires": 1,
     "params": {"probability_per_word": 0.5}},
    {"op": "truncate", "tools": ["list_notes", "get_note"], "persistence": "transient", "activation_p": 1.0,
     "max_fires": 1, "params": {"percent": 50}},
    {"op": "small_delta", "tools": ["search_products"], "persistence": "intermittent", "activation_p": 0.5,
     "deactivation_p": 0.5},
    {"op": "malformed_json", "tools": ["search_notes"], "persistence": "transient", "activation_p": 1.0, "max_fires": 1},
    {"op": "drop_call", "tools": ["list_orders"], "persistence": "transient", "activation_p": 1.0, "max_fires": 1},
]}
# (schedule, seed, target, server, calls); paper seeds were chosen so no 30 s OP5 delay is drawn.
SESSIONS = [
    ("profiles/paper_opp.yaml", "dev:0", None, "inventory", INVENTORY_CALLS),
    ("profiles/paper_opp.yaml", "dev:5", None, "inventory", INVENTORY_CALLS),
    ("profiles/paper_opp.yaml", "dev:22", None, "inventory", INVENTORY_CALLS),
    ("profiles/paper_opp.yaml", "dev:7", None, "notes", NOTES_CALLS),
    ("profiles/paper_opp_scoped.yaml", "dev:11", "get_price", "inventory", INVENTORY_CALLS),
    ("profiles/empty.yaml", None, None, "notes", NOTES_CALLS),
    (RULES, None, None, "inventory", INVENTORY_CALLS),
    (RULES, None, None, "notes", NOTES_CALLS),
]


def _readlines(process: subprocess.Popen, wait: float) -> list[str]:
    """Raw stdout lines available within ``wait`` seconds (more lines are read while they keep coming)."""
    lines = []
    while True:
        readable, _, _ = select.select([process.stdout], [], [], wait if not lines else 0.15)
        if not readable:
            return lines
        line = process.stdout.readline()
        if not line:
            return lines
        lines.append(line)


def run_session(schedule, seed, target, server, calls, shim=None, wait=1.5) -> dict:
    """Run one scripted client session; return raw stdout lines per request and the normalized log."""
    with tempfile.TemporaryDirectory(prefix="chaos-session-") as tmp:
        tmp_path = Path(tmp)
        if isinstance(schedule, dict):
            schedule_path = tmp_path / "schedule.yaml"
            schedule_path.write_text(yaml.safe_dump(schedule), encoding="utf-8")
        else:
            schedule_path = ROOT / schedule
        log = tmp_path / "proxy.jsonl"
        command = [sys.executable, "-m", "mcp_fault_bench", "proxy", "--schedule", str(schedule_path), "--log", str(log)]
        if seed is not None:
            command += ["--seed", seed]
        if target:
            command += ["--target", target]
        if shim:
            command += ["--shim", str(shim)]
        environment = {**os.environ, "PYTHONPATH": str(ROOT), "CHAOS_STATE_FILE": str(tmp_path / "state.json")}
        process = subprocess.Popen([*command, "--", sys.executable, "-m", f"servers.{server}"], cwd=ROOT,
                                   env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, bufsize=1)
        transcript = []
        try:
            requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                        {"jsonrpc": "2.0", "method": "notifications/initialized"},
                        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
            requests += [{"jsonrpc": "2.0", "id": 10 + index, "method": "tools/call",
                          "params": {"name": name, "arguments": arguments}} for index, (name, arguments) in enumerate(calls)]
            for request in requests:
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
                transcript.append(_readlines(process, wait if "id" in request else 0.2))
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        events = []
        for line in log.read_text(encoding="utf-8").splitlines() if log.exists() else []:
            event = json.loads(line)
            events.append({key: value for key, value in event.items() if key not in VOLATILE})
        return {"stdout": transcript, "log": events}


def main() -> None:
    print(json.dumps([run_session(*session) for session in SESSIONS], indent=1))


if __name__ == "__main__":
    main()
