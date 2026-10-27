"""A small, protocol-aware stdio proxy for deterministic MCP fault injection."""

from __future__ import annotations

import json
import os
import queue
import random
import re
import string
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from .shim import Shim, load_shim_config

OPS = {
    "small_delta": "OP1", "random_value": "OP2", "wrong_type": "OP3",
    "error": "OP4", "delay": "OP5", "timeout": "OP6", "drop_call": "OP6",
    "malformed_json": "extra", "truncate": "extra", "schema_drift": "extra",
}


def load_schedule(path: str | None) -> dict[str, Any]:
    """Read a YAML schedule, using an empty schedule when no path is given."""
    if not path:
        return {"seed": 0, "faults": []}
    with Path(path).open(encoding="utf-8") as stream:
        schedule = yaml.safe_load(stream) or {}
    schedule.setdefault("seed", 0)
    schedule.setdefault("faults", [])
    return schedule


class ProfileDrawEngine:
    """MCP-Injector draw semantics: hold one weighted profile entry at a time.

    Mirrors ``Injector.select_injector`` / ``on_call_tool`` in the reference middleware, with every
    random decision seeded: draws by (seed, draw index), firing and release by (seed, call index).
    Only calls to in-scope tools advance the call index and the held state.
    """

    def __init__(self, schedule: dict[str, Any], seed: Any = None, target: str | None = None):
        self.seed = schedule.get("seed", 0) if seed is None else seed
        self.entries: list[dict[str, Any]] = schedule["entries"]
        self.weights = [float(entry["weight"]) for entry in self.entries]
        self.scope = "tools" if target else schedule.get("scope", "global")
        self.tools = [target] if target else list(schedule.get("tools", ["*"]))
        self.held: dict[str, Any] | None = None
        self.held_draw = -1
        self.draws = 0
        self.calls = 0

    def in_scope(self, tool: str) -> bool:
        return self.scope != "tools" or tool in self.tools or "*" in self.tools

    def _draw(self) -> None:
        rng = random.Random(f"{self.seed}:draw:{self.draws}")
        self.held = self.entries[rng.choices(range(len(self.entries)), weights=self.weights, k=1)[0]]
        self.held_draw = self.draws
        self.draws += 1

    def choose(self, tool: str) -> dict[str, Any] | None:
        """Return the decision for one tools/call, or None when the tool is out of scope."""
        if not self.in_scope(tool):
            return None
        call_index = self.calls
        self.calls += 1
        rng = random.Random(f"{self.seed}:call:{call_index}")
        release_roll, fire_roll = rng.random(), rng.random()
        if self.held is None:
            self._draw()
            entry, draw_index = self.held, self.held_draw
        else:
            entry, draw_index = self.held, self.held_draw
            # Reference: a held INTERMITTENT entry is released with deactivation_p before the call,
            # but still applies to that call; the next call draws a new entry.
            if entry["persistence"] == "intermittent" and release_roll <= float(entry.get("deactivation_p", 0.3)):
                self.held = None
        assert entry is not None
        persistence = entry["persistence"]
        fired = persistence == "permanent" or fire_roll <= float(entry.get("activation_p", 1.0))
        if persistence == "transient":
            self.held = None
        params = dict(entry.get("params", {}))
        params["_rng_seed"] = f"{self.seed}:mutate:{call_index}"
        return {"op": entry["op"], "params": params, "persistence": persistence, "fired": fired,
                "draw_index": draw_index, "call_index": call_index,
                "entry": {"paper_type": entry.get("paper_type"), "persistence": persistence,
                          "label": entry_label(entry)}}


def first_draw(schedule: dict[str, Any], seed_string: Any) -> str | None:
    """Label of the entry ProfileDrawEngine draws first (draw_index 0) for a seed, without running anything.

    The draw depends only on the seed string and the entry weights (not on tool names, target or timing),
    so every model and both proxies of a multi-server task see this entry on their first in-scope call.
    """
    entries = schedule.get("entries") or []
    if not entries:
        return None
    rng = random.Random(f"{seed_string}:draw:0")
    index = rng.choices(range(len(entries)), weights=[float(entry["weight"]) for entry in entries], k=1)[0]
    return entry_label(entries[index])


def entry_label(entry: dict[str, Any]) -> str:
    """Short family label such as ``OP4/permanent``."""
    paper_type = entry.get("paper_type") or OPS.get(entry.get("op", ""), "extra")
    return f"{paper_type.split('_')[0]}/{entry['persistence']}"


class FaultEngine:
    """Select schedule faults with stable per-tool call counters and RNG seeds."""

    def __init__(self, schedule: dict[str, Any]):
        self.seed = schedule.get("seed", 0)
        self.faults = schedule.get("faults", [])
        self.counts: dict[str, int] = {}
        self.active: set[tuple[str, int]] = set()
        self.fire_counts: dict[tuple[str, int], int] = {}

    def choose(self, tool: str) -> tuple[int, dict[str, Any]] | None:
        """Return the first activated matching fault for this tool call."""
        call_index = self.counts.get(tool, 0)
        self.counts[tool] = call_index + 1
        for fault_index, fault in enumerate(self.faults):
            targets = fault.get("tools", ["*"])
            if tool not in targets and "*" not in targets:
                continue
            if call_index < int(fault.get("after_calls", 0)):
                continue

            key = (tool, fault_index)
            fired_count = self.fire_counts.get(key, 0)
            max_fires = fault.get("max_fires")
            if max_fires is None and _persistence_type(fault) == "transient":
                max_fires = 1
            if max_fires is not None and fired_count >= int(max_fires):
                continue

            persistence = _persistence_type(fault)
            params = _persistence_params(fault)
            rng = random.Random(f"{self.seed}:{tool}:{call_index}:{fault_index}")
            activation = float(params.get("activation_p", fault.get("activation_p", 1.0)))
            if persistence == "permanent":
                if key not in self.active and rng.random() < activation:
                    self.active.add(key)
                is_active = key in self.active
            elif persistence == "intermittent":
                if key in self.active:
                    deactivation = float(params.get("deactivation_p", fault.get("deactivation_p", 0.3)))
                    if rng.random() < deactivation:
                        self.active.remove(key)
                elif rng.random() < activation:
                    self.active.add(key)
                is_active = key in self.active
            else:
                is_active = rng.random() < activation

            if is_active:
                self.fire_counts[key] = fired_count + 1
                selected = dict(fault)
                selected["params"] = dict(fault.get("params", {}))
                selected["params"]["_rng_seed"] = f"{self.seed}:{tool}:{call_index}:{fault_index}"
                return fault_index, selected
        return None


def _persistence_type(fault: dict[str, Any]) -> str:
    persistence = fault.get("persistence", "transient")
    return persistence.get("type", "transient").lower() if isinstance(persistence, dict) else persistence.lower()


def _persistence_params(fault: dict[str, Any]) -> dict[str, Any]:
    persistence = fault.get("persistence", {})
    return persistence if isinstance(persistence, dict) else {}


def _mutate(response: dict[str, Any], fault: dict[str, Any]) -> dict[str, Any]:
    """Apply a result mutation in place and return the JSON-RPC response."""
    op = fault["op"]
    params = fault.get("params", {})
    if op == "error":
        message = params.get("message", "Access Denied to: tool (service unavailable 503)")
        if params.get("style", "tool_result") == "jsonrpc":
            return {"jsonrpc": "2.0", "id": response.get("id"), "error": {"code": -32003, "message": message}}
        response["result"] = {"content": [{"type": "text", "text": message}], "isError": True}
        return response

    result = response.get("result")
    if not isinstance(result, dict):
        return response
    for content in result.get("content", []):
        if not isinstance(content, dict) or not isinstance(content.get("text"), str):
            continue
        text = content["text"]
        rng = random.Random(params.get("_rng_seed", f"{params.get('seed', 0)}:{text}"))
        if op in ("small_delta", "random_value") and "probability_per_word" in params:
            content["text"] = _paper_perturb(op, text, float(params["probability_per_word"]), rng)
        elif op == "small_delta":
            content["text"] = re.sub(r"\d+", lambda match: str(int(match.group()) + (1 if rng.random() < 0.5 else -1)), text)
        elif op == "random_value":
            words = re.findall(r"\b[\w.-]+\b", text)
            if words:
                old = words[0]
                replacement = str(round(rng.uniform(1, 99), 2)) if old[0].isdigit() else "uncertain"
                content["text"] = text.replace(old, replacement, 1)
        elif op == "wrong_type":
            # The reference wraps a string result as {"text": <original>}.
            content["text"] = json.dumps({"text": text})
        elif op == "truncate":
            percent = max(0.0, min(100.0, float(params.get("percent", 50))))
            content["text"] = text[:max(1, int(len(text) * percent / 100))]
    return response


def _paper_perturb(op: str, text: str, probability: float, rng: random.Random) -> str:
    """OP1/OP2 as in MCP-Injector: per whitespace word, change one letter or replace the word."""
    words = []
    for word in text.split():
        if rng.random() <= probability:
            if op == "small_delta":
                index = rng.randint(0, len(word) - 1)
                word = word[:index] + rng.choice(string.ascii_letters) + word[index + 1:]
            else:
                word = "".join(rng.choice(string.ascii_letters) for _ in range(len(word)))
        words.append(word)
    return " ".join(words)


def _drift_tools(response: dict[str, Any], faults: list[dict[str, Any]]) -> dict[str, Any]:
    """Rename configured arguments in matching tools/list input schemas."""
    result = response.get("result")
    if not isinstance(result, dict):
        return response
    for fault in faults:
        if fault.get("op") != "schema_drift":
            continue
        targets = fault.get("tools", ["*"])
        params = fault.get("params", {})
        old_name = params.get("rename")
        new_name = params.get("to", "renamed")
        for tool in result.get("tools", []):
            if tool.get("name") not in targets and "*" not in targets:
                continue
            schema = tool.setdefault("inputSchema", {})
            properties = schema.setdefault("properties", {})
            if old_name in properties:
                properties[new_name] = properties.pop(old_name)
            if old_name in schema.get("required", []):
                schema["required"] = [new_name if name == old_name else name for name in schema["required"]]
            changed_field = params.get("field", new_name)
            if "type" in params and changed_field in properties:
                properties[changed_field]["type"] = params["type"]
    return response


def _matches(fault: dict[str, Any], tool: str) -> bool:
    targets = fault.get("tools", ["*"])
    return tool in targets or "*" in targets


def _write_event(log: Any, event: dict[str, Any]) -> None:
    log.write(json.dumps(event, separators=(",", ":")) + "\n")
    log.flush()


def run_proxy(command: list[str], schedule_path: str | None = None, log_path: str | None = None,
              seed: str | None = None, target: str | None = None, shim_path: str | None = None) -> int:
    """Relay stdio JSON-RPC to an upstream process and inject scheduled faults.

    With ``shim_path`` the resilience shim (mcp_fault_bench/shim.py) sits between the agent and the fault layer.
    Without it the relay is unchanged.
    """
    schedule = load_schedule(schedule_path)
    if seed is not None:
        schedule["seed"] = seed
    profile = schedule.get("kind") == "profile_draw"
    engine: Any = ProfileDrawEngine(schedule, target=target) if profile else FaultEngine(schedule)
    run_id = str(uuid.uuid4())
    log = open(log_path or os.getenv("CHAOS_LOG", os.devnull), "a", encoding="utf-8")
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, text=True, bufsize=1)
    # id -> {tool, fault, start, args, is_list, extra}; ``extra`` carries profile-draw log fields.
    pending: dict[str, dict[str, Any]] = {}
    lock = threading.Lock()
    upstream_lock = threading.Lock()
    client_lock = threading.Lock()
    schema_rules = [fault for fault in schedule.get("faults", []) if fault.get("op") == "schema_drift"]
    shim: Shim | None = None
    downstream: queue.Queue = queue.Queue()

    def event(tool: str, args: dict[str, Any], fault: dict[str, Any] | None, latency: float, outcome: str,
              method: str = "tools/call", extra: dict[str, Any] | None = None, request_id: Any = None) -> None:
        fired = fault.get("op") if fault else None
        record = {"ts": time.time(), "run_id": run_id, "method": method, "tool": tool, "args": args,
                  "fault": fired, "persistence": fault.get("persistence") if fault else None,
                  "latency": latency, "outcome": outcome}
        if extra:
            record.update(extra)
        if shim is not None and request_id is not None:
            record["downstream_id"] = request_id
            shim.observe(request_id, fired)
        with lock:
            _write_event(log, record)

    def write_client(message: dict[str, Any] | str) -> None:
        text = message if isinstance(message, str) else json.dumps(message, separators=(",", ":")) + "\n"
        with client_lock:
            sys.stdout.write(text)
            sys.stdout.flush()

    def to_client(message: dict[str, Any] | str) -> None:
        if shim is not None:
            shim.from_downstream(message)
        else:
            write_client(message)

    def write_log(record: dict[str, Any]) -> None:
        with lock:
            _write_event(log, record)

    if shim_path:
        shim = Shim(load_shim_config(shim_path), downstream.put, write_client, write_log, run_id)

    def to_server(line: str) -> None:
        assert process.stdin
        with upstream_lock:
            try:
                process.stdin.write(line)
                process.stdin.flush()
            except (BrokenPipeError, ValueError):
                pass

    def profile_call(message: dict[str, Any], tool: str, args: dict[str, Any], line: str) -> bool:
        """Handle a tools/call under a profile-draw schedule; True when the line was consumed."""
        request_id = message.get("id")
        decision = engine.choose(tool)
        extra = {"draw_index": None, "entry": None, "fired": False}
        if decision is not None:
            extra = {"draw_index": decision["draw_index"], "entry": decision["entry"], "fired": decision["fired"]}
        fault = decision if decision and decision["fired"] else None
        started = time.monotonic()
        op = fault["op"] if fault else None
        if op == "error":
            # Reference OP4 raises ToolError before calling the server; FastMCP returns it as isError.
            event(tool, args, fault, 0.0, "faulted", extra=extra, request_id=request_id)
            if request_id is not None:
                to_client({"jsonrpc": "2.0", "id": request_id, "result": {
                    "content": [{"type": "text", "text": f"Access Denied to: {tool}"}], "isError": True}})
            return True
        if request_id is not None:
            with lock:
                pending[str(request_id)] = {"tool": tool, "fault": fault or {}, "start": started, "args": args,
                                            "is_list": False, "extra": extra}
        if op == "drop_call":
            # Reference OP6 awaits the server first (side effects happen), then never answers.
            event(tool, args, fault, 0.0, "dropped", extra=extra, request_id=request_id)
        if op == "delay":
            # Sleep, then forward; a timer keeps other requests flowing meanwhile.
            timer = threading.Timer(float(fault["params"].get("seconds", 30)), to_server, args=(line,))
            timer.daemon = True
            timer.start()
            return True
        return False

    def client_to_server() -> None:
        assert process.stdin
        for line in sys.stdin if shim is None else iter(downstream.get, None):
            upstream_line = line
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    continue
                method = message.get("method")
                request_id = message.get("id")
                if method == "tools/call" and profile:
                    params = message.get("params", {})
                    if profile_call(message, params.get("name", "unknown"), dict(params.get("arguments", {})), line):
                        continue
                elif method == "tools/call":
                    params = message.get("params", {})
                    tool = params.get("name", "unknown")
                    args = dict(params.get("arguments", {}))
                    matching_schema = next((fault for fault in schema_rules if _matches(fault, tool)), None)
                    schema_params = matching_schema.get("params", {}) if matching_schema else {}
                    old_parameter = schema_params.get("rename")
                    new_parameter = schema_params.get("to", "renamed")
                    if matching_schema and old_parameter in args:
                        chosen = engine.choose(tool)
                    else:
                        chosen = None
                        if matching_schema and new_parameter in args:
                            args[old_parameter] = args.pop(new_parameter)
                            params["arguments"] = args
                            message["params"] = params
                            upstream_line = json.dumps(message) + "\n"
                        elif not matching_schema:
                            chosen = engine.choose(tool)
                    if chosen:
                        _, fault = chosen
                        if fault["op"] == "schema_drift":
                            event(tool, args, fault, 0, "invalid_params", request_id=request_id)
                            to_client({"jsonrpc": "2.0", "id": request_id, "error": {
                                "code": -32602, "message": "Invalid params: parameter name changed by schema_drift"}})
                            continue
                        if fault["op"] == "drop_call":
                            # Forward (side effects happen) and swallow the response, like the reference.
                            event(tool, args, fault, 0, "dropped", request_id=request_id)
                        if fault["op"] == "timeout":
                            timeout_seconds = float(fault.get("params", {}).get("seconds", 10))
                            event(tool, args, fault, timeout_seconds, "dropped", request_id=request_id)
                        if request_id is not None:
                            with lock:
                                pending[str(request_id)] = {"tool": tool, "fault": fault, "start": time.monotonic(),
                                                            "args": args, "is_list": False, "extra": None}
                    elif request_id is not None:
                        with lock:
                            pending[str(request_id)] = {"tool": tool, "fault": {}, "start": time.monotonic(),
                                                        "args": args, "is_list": False, "extra": None}
                elif method == "tools/list" and request_id is not None:
                    with lock:
                        pending[str(request_id)] = {"tool": "__tools_list__", "fault": {}, "start": time.monotonic(),
                                                    "args": {}, "is_list": True, "extra": None}
            except (json.JSONDecodeError, AttributeError):
                pass
            to_server(upstream_line)
        with upstream_lock:
            process.stdin.close()

    def server_to_client() -> None:
        assert process.stdout
        for line in process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                to_client(line)
                continue
            request_id = str(message.get("id")) if isinstance(message, dict) and "id" in message else None
            with lock:
                info = pending.pop(request_id, None) if request_id else None
            if info:
                tool, fault, start, args, is_list = info["tool"], info["fault"], info["start"], info["args"], info["is_list"]
                fired = fault.get("op")
                if fired == "drop_call":
                    continue
                if fired == "timeout":
                    time.sleep(float(fault.get("params", {}).get("seconds", 10)))
                    continue
                if fired == "delay" and not profile:
                    params = fault.get("params", {})
                    if "min_seconds" in params or "max_seconds" in params:
                        rng = random.Random(params.get("_rng_seed", "0"))
                        seconds = rng.uniform(float(params.get("min_seconds", 1)), float(params.get("max_seconds", 1)))
                    else:
                        seconds = float(params.get("seconds", 1))
                    time.sleep(seconds)
                if fired and fired not in ("delay", "malformed_json"):
                    message = _mutate(message, fault)

                if is_list:
                    listed = {tool_item.get("name") for tool_item in message.get("result", {}).get("tools", [])}
                    matching = [rule for rule in schema_rules if any(_matches(rule, name) for name in listed)]
                    if matching:
                        message = _drift_tools(message, matching)
                        fired = "schema_drift"
                        fault = matching[0]
                        tool = next((name for name in listed if _matches(fault, name)), "__tools_list__")

                event(tool, args, fault if fired else None, time.monotonic() - start, "faulted" if fired else "ok",
                      method="tools/list" if is_list else "tools/call", extra=info["extra"], request_id=request_id)
                if fired == "malformed_json":
                    # A malformed notification is ignored by tolerant clients. The following valid
                    # JSON-RPC error completes this request id and leaves the connection usable.
                    to_client('{"jsonrpc":"2.0","id":\n' + json.dumps({"jsonrpc": "2.0", "id": message.get("id"), "error": {
                        "code": -32004, "message": "Injected malformed response; retry the call"}}) + "\n")
                    continue
            to_client(message)

    def agent_to_shim() -> None:
        assert shim is not None
        for line in sys.stdin:
            shim.from_client(line)
        shim.close()
        downstream.put(None)

    threads = [threading.Thread(target=client_to_server, daemon=True),
               threading.Thread(target=server_to_client, daemon=True)]
    if shim is not None:
        threads.append(threading.Thread(target=agent_to_shim, daemon=True))
    client_thread, server_thread = threads[0], threads[1]
    for thread in threads:
        thread.start()
    if shim is not None:
        threads[2].join()
    client_thread.join()
    server_thread.join()
    log.close()
    return process.wait()
