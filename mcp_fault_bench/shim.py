"""Opt-in client-side resilience shim.

Two modes (``mode`` in the config):

- ``classify`` (profiles/shim.yaml, pre-registered in docs/preregistration-shim.md): every agent call is
  forwarded exactly once, outputs are not validated, and only the error text the agent receives is rewritten:
  errors classified PERMANENT name a fallback tool. Successful responses pass through unchanged.
- ``retry`` (profiles/shim_retry.yaml): retry, per-attempt timeout, output validation, fallback hints.

Placement inside the proxy process: agent -> shim -> fault injector -> server. The shim sees faulted
responses, and every retry is a new tools/call (new JSON-RPC id) through the fault engine, so it advances
draw and held state exactly like an agent retry would.
"""

from __future__ import annotations

import itertools
import json
import queue
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import yaml

MODES = ("classify", "retry")
DEFAULTS: dict[str, Any] = {"mode": "retry", "retry": {"max_retries": 3, "backoff_s": [0.5, 1.0, 2.0]}, "attempt_timeout_s": 35,
                            "non_idempotent": [], "verify_with": {}, "validate": "json", "schemas": {}, "fallbacks": {}}
# JSON-RPC protocol errors are client mistakes (bad method, bad params), not server faults: passed through.
PROTOCOL_ERRORS = {-32700, -32600, -32601, -32602}
# Classify mode: auth, permission and not-found errors are PERMANENT on the first occurrence.
PERMANENT_PATTERN = re.compile(r"access denied|forbidden|unauthori[sz]ed|permission denied|not found"
                               r"|\b401\b|\b403\b|\b404\b", re.IGNORECASE)
NO_FALLBACK = "No working alternative tool is known; complete what you can and report what could not be done."
TYPES: dict[str, Callable[[Any], bool]] = {
    "string": lambda value: isinstance(value, str),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "null": lambda value: value is None,
}


def load_shim_config(path: str) -> dict[str, Any]:
    """Read a shim YAML config, filling defaults for missing keys."""
    with Path(path).open(encoding="utf-8") as stream:
        loaded = yaml.safe_load(stream) or {}
    config = {**DEFAULTS, **loaded}
    config["retry"] = {**DEFAULTS["retry"], **(loaded.get("retry") or {})}
    if config["mode"] not in MODES:
        raise ValueError(f"shim mode must be one of {', '.join(MODES)}, not {config['mode']!r}")
    return config


def check_schema(value: Any, schema: Any, path: str = "value") -> str | None:
    """Return why ``value`` does not match ``schema`` (a type name, a list of names, or a dict), else None."""
    if isinstance(schema, (str, list)):
        names = [schema] if isinstance(schema, str) else schema
        if any(TYPES[str(name)](value) for name in names):
            return None
        return f"{path} is {_type_name(value)}, expected {' or '.join(map(str, names))}"
    kind = schema.get("type", "object")
    mismatch = check_schema(value, kind, path)
    if mismatch:
        return mismatch
    if kind == "object":
        for key, expected in (schema.get("required") or {}).items():
            if key not in value:
                return f"{path} is missing required key '{key}'"
            mismatch = check_schema(value[key], expected, f"{path}.{key}")
            if mismatch:
                return mismatch
        if "values" in schema:
            for key, item in value.items():
                mismatch = check_schema(item, schema["values"], f"{path}.{key}")
                if mismatch:
                    return mismatch
    if kind == "array" and "items" in schema:
        for index, item in enumerate(value):
            mismatch = check_schema(item, schema["items"], f"{path}[{index}]")
            if mismatch:
                return mismatch
    return None


def _type_name(value: Any) -> str:
    return next((name for name, test in TYPES.items() if name != "integer" and test(value)), type(value).__name__)


def _text(result: dict[str, Any]) -> str:
    return "".join(item.get("text", "") for item in result.get("content") or []
                   if isinstance(item, dict) and isinstance(item.get("text"), str))


def classify(config: dict[str, Any], tool: str, response: dict[str, Any]) -> tuple[str, str | None]:
    """("ok" | "error" | "validation" | "protocol", reason) for one downstream response."""
    error = response.get("error")
    if isinstance(error, dict):
        kind = "protocol" if error.get("code") in PROTOCOL_ERRORS else "error"
        return kind, str(error.get("message", "JSON-RPC error"))
    result = response.get("result")
    if not isinstance(result, dict):
        return "validation", "response has no result object"
    if result.get("isError"):
        return "error", _text(result) or "tool returned isError"
    if config.get("validate") != "json":
        return "ok", None
    text = _text(result)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as problem:
        return "validation", f"response text is not valid JSON ({problem.msg} at char {problem.pos})"
    schema = (config.get("schemas") or {}).get(tool)
    mismatch = check_schema(value, schema) if schema is not None else None
    return ("validation", mismatch) if mismatch else ("ok", None)


def _seconds(value: float) -> str:
    return f"{float(value):g} s"


class Shim:
    """Correlates agent tools/call requests with downstream attempts; every agent request gets one answer."""

    def __init__(self, config: dict[str, Any], send_downstream: Callable[[str], None],
                 write_client: Callable[[dict[str, Any]], None], log: Callable[[dict[str, Any]], None],
                 run_id: str):
        self.config = config
        self.send_downstream = send_downstream
        self.write_client = write_client
        self.log = log
        self.run_id = run_id
        self.prefix = f"chaos-shim-{uuid.uuid4().hex[:8]}-"
        self.counter = itertools.count(1)
        self.lock = threading.Lock()
        self.waiting: dict[str, queue.Queue] = {}
        self.attempt_faults: dict[str, str | None] = {}
        self.workers: list[threading.Thread] = []
        # Classify mode: consecutive errors per tool, and tools currently classified PERMANENT.
        self.error_streak: dict[str, int] = {}
        self.permanent: set[str] = set()

    # -------------------------------------------------------------------------------- agent side
    def from_client(self, line: str) -> None:
        """Handle one line from the agent: tools/call requests get a worker, everything else passes through."""
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            message = None
        if isinstance(message, dict) and message.get("method") == "tools/call" and message.get("id") is not None:
            worker = threading.Thread(target=self._call, args=(message,), daemon=True)
            with self.lock:
                self.workers = [thread for thread in self.workers if thread.is_alive()] + [worker]
            worker.start()
            return
        self.send_downstream(line)

    def close(self) -> None:
        """Wait for in-flight calls (each is bounded by its attempt timeouts and backoffs)."""
        with self.lock:
            workers = list(self.workers)
        for worker in workers:
            worker.join()

    # -------------------------------------------------------------------------------- server side
    def observe(self, downstream_id: str, fault: str | None) -> None:
        """Record which fault (if any) the injector applied to one downstream attempt."""
        if isinstance(downstream_id, str) and downstream_id.startswith(self.prefix):
            with self.lock:
                self.attempt_faults[downstream_id] = fault

    def from_downstream(self, message: dict[str, Any] | str) -> None:
        """Route a message from the fault layer: attempt responses to their worker, the rest to the agent."""
        if isinstance(message, str):
            for line in message.splitlines():
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue  # an unparseable line cannot be correlated; a client-side wrapper drops it
                if isinstance(parsed, dict):
                    self.from_downstream(parsed)
            return
        message_id = message.get("id")
        if isinstance(message_id, str) and message_id.startswith(self.prefix):
            with self.lock:
                waiter = self.waiting.pop(message_id, None)
            if waiter is not None:
                waiter.put(message)
            return  # late response for an abandoned attempt (or a duplicate): never forwarded
        self.write_client(message)

    # -------------------------------------------------------------------------------- one agent call
    def _attempt(self, params: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        downstream_id = f"{self.prefix}{next(self.counter)}"
        waiter: queue.Queue = queue.Queue(maxsize=1)
        with self.lock:
            self.waiting[downstream_id] = waiter
        self.send_downstream(json.dumps({"jsonrpc": "2.0", "id": downstream_id, "method": "tools/call",
                                         "params": params}) + "\n")
        try:
            return downstream_id, waiter.get(timeout=float(self.config["attempt_timeout_s"]))
        except queue.Empty:
            with self.lock:
                abandoned = self.waiting.pop(downstream_id, None)
            if abandoned is None:  # the response was claimed between the timeout and the pop; it is being put
                return downstream_id, waiter.get(timeout=5)
            return downstream_id, None

    def _call(self, message: dict[str, Any]) -> None:
        if self.config["mode"] == "classify":
            self._classify_call(message)
            return
        request_id = message["id"]
        params = message.get("params") or {}
        tool = str(params.get("name", "unknown"))
        idempotent = tool not in set(self.config.get("non_idempotent") or [])
        retry = self.config["retry"]
        backoff = list(retry.get("backoff_s") or [0.0])
        max_retries = int(retry.get("max_retries", 0)) if idempotent else 0
        started = time.monotonic()
        attempts = retried = validation_failures = 0
        faults: list[str | None] = []
        timed_out = False
        kind, reason, response = "error", None, None
        while True:
            attempts += 1
            downstream_id, response = self._attempt(params)
            with self.lock:
                faults.append(self.attempt_faults.pop(downstream_id, None))
            if response is None:
                timed_out = True
                break
            kind, reason = classify(self.config, tool, response)
            if kind == "validation":
                validation_failures += 1
            if kind in ("ok", "protocol") or attempts > max_retries:
                break
            time.sleep(float(backoff[min(attempts - 1, len(backoff) - 1)]))
            retried += 1

        if kind in ("ok", "protocol") and response is not None:
            answer = {**response, "id": request_id}  # the validated result, unchanged
        else:
            answer = {"jsonrpc": "2.0", "id": request_id, "result": {
                "content": [{"type": "text", "text": self._failure_text(tool, attempts, kind, reason, timed_out,
                                                                        idempotent)}], "isError": True}}
        final = "ok" if kind == "ok" and not timed_out else "error"
        self.log({"ts": time.time(), "run_id": self.run_id, "layer": "shim", "method": "tools/call", "tool": tool,
                  "args": dict(params.get("arguments") or {}), "latency": time.monotonic() - started,
                  "outcome": final, "shim": {"attempts": attempts, "retried": retried,
                                             "validation_failures": validation_failures, "timed_out": timed_out,
                                             "final": final, "attempt_faults": faults,
                                             "reason": None if final == "ok" else reason}})
        self.write_client(answer)

    def _failure_text(self, tool: str, attempts: int, kind: str, reason: str | None, timed_out: bool,
                      idempotent: bool) -> str:
        if timed_out:
            text = (f"[resilience-shim] {tool} did not respond within "
                    f"{_seconds(self.config['attempt_timeout_s'])} (no retry).")
        else:
            plural = "attempt" if attempts == 1 else "attempts"
            text = f"[resilience-shim] {tool} failed after {attempts} {plural}: {(reason or 'error').rstrip('.')}."
            if kind == "validation":
                text += " The returned value was withheld because it failed validation."
        alternatives = (self.config.get("fallbacks") or {}).get(tool) or []
        if alternatives:
            text += f" Alternatives: {', '.join(alternatives)}."
        if not idempotent:
            check = (self.config.get("verify_with") or {}).get(tool)
            text += (f" {tool} is not idempotent and was not retried: the side effect may have happened;"
                     f" check {check or 'the server state'} before retrying.")
        return text

    # -------------------------------------------------------------------------------- classify mode
    def _classify_call(self, message: dict[str, Any]) -> None:
        """Forward once; pass successes and protocol errors through, rewrite errors classified PERMANENT."""
        request_id = message["id"]
        params = message.get("params") or {}
        tool = str(params.get("name", "unknown"))
        started = time.monotonic()
        downstream_id, response = self._attempt(params)
        with self.lock:
            fault = self.attempt_faults.pop(downstream_id, None)
        if response is None:
            kind, reason = "error", f"UNRESPONSIVE: no response within {_seconds(self.config['attempt_timeout_s'])}"
        else:
            kind, reason = classify({**self.config, "validate": "off"}, tool, response)
        fallbacks: list[str] | None = None
        with self.lock:
            if kind == "ok":
                self.error_streak.pop(tool, None)
                self.permanent.discard(tool)
            if kind == "error":
                self.error_streak[tool] = self.error_streak.get(tool, 0) + 1
                if response is None:
                    shim_class = "unresponsive"
                elif PERMANENT_PATTERN.search(reason or "") or self.error_streak[tool] >= 2:
                    shim_class = "permanent"
                else:
                    shim_class = "pass"
                if shim_class != "pass":
                    self.permanent.add(tool)
                    fallbacks = [name for name in (self.config.get("fallbacks") or {}).get(tool) or []
                                 if name not in self.permanent]
            else:
                shim_class = "pass"
        if shim_class == "pass" and response is not None:
            answer = {**response, "id": request_id}  # unchanged apart from the agent's request id
        else:
            answer = {"jsonrpc": "2.0", "id": request_id, "result": {
                "content": [{"type": "text", "text": self._permanent_text(tool, reason or "error", fallbacks or [])}],
                "isError": True}}
        final = "ok" if kind == "ok" else "error"
        self.log({"ts": time.time(), "run_id": self.run_id, "layer": "shim", "method": "tools/call", "tool": tool,
                  "args": dict(params.get("arguments") or {}), "latency": time.monotonic() - started,
                  "outcome": final, "shim_class": shim_class, "fallback_named": fallbacks or None,
                  "shim": {"mode": "classify", "attempts": 1, "retried": 0, "validation_failures": 0,
                           "timed_out": response is None, "final": final, "attempt_faults": [fault],
                           "reason": None if final == "ok" else reason}})
        self.write_client(answer)

    def _permanent_text(self, tool: str, error: str, fallbacks: list[str]) -> str:
        text = f"PERMANENT: {tool} failed ({error}). Do not retry {tool}; it will not recover in this session. "
        text += f"Use fallback tool {' or '.join(fallbacks)} instead." if fallbacks else NO_FALLBACK
        if tool in set(self.config.get("non_idempotent") or []):
            check = (self.config.get("verify_with") or {}).get(tool) or "the server state"
            text += f" The order may or may not have been placed; check {check} before ordering again."
        return text
