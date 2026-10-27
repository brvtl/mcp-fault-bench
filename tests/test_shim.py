"""Resilience shim, retry mode (profiles/shim_retry.yaml): retry, validation, non-idempotent calls, timeouts,
concurrency, and shim-off identity. Classify mode is in tests/test_shim_classify.py.

Seeds are dev strings ("dev:<n>") only.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from mcp_fault_bench.shim import check_schema, classify, load_shim_config
from servers import inventory, notes
from tests.proxy_sessions import SESSIONS, run_session

ROOT = Path(__file__).resolve().parents[1]
SHIM = load_shim_config(str(ROOT / "profiles" / "shim_retry.yaml"))


def _ok(value):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(value)}],
                                                   "isError": False}}


def test_every_server_tool_has_a_schema_that_accepts_its_clean_output():
    calls = {"search_products": {"category": "tea"}, "get_product": {"sku": "SKU-731"}, "get_price": {"sku": "SKU-731"},
             "get_price_v2": {"sku": "SKU-731"}, "get_stock": {"sku": "SKU-731"},
             "place_order": {"sku": "SKU-731", "quantity": 1}, "list_orders": {}}
    assert set(SHIM["schemas"]) == {tool["name"] for tool in inventory.TOOLS + notes.TOOLS}
    for name, arguments in calls.items():
        assert classify(SHIM, name, _ok(inventory.call_tool(name, arguments))) == ("ok", None), name
    notes.NOTES.clear()
    for name, arguments in (("put_note", {"key": "k", "value": "v"}), ("get_note", {"key": "k"}),
                            ("get_note", {"key": "missing"}), ("list_notes", {}), ("search_notes", {"query": "v"})):
        assert classify(SHIM, name, _ok(notes.call_tool(name, arguments))) == ("ok", None), name
    notes.NOTES.clear()
    inventory.ORDERS.clear()


def test_fallbacks_name_only_real_tools():
    names = {tool["name"] for tool in inventory.TOOLS + notes.TOOLS}
    for tool, alternatives in SHIM["fallbacks"].items():
        assert tool in names and set(alternatives) <= names and tool not in alternatives


def test_validation_reasons():
    assert "missing required key 'price'" in check_schema({"sku": "A"}, SHIM["schemas"]["get_price"])
    assert "expected number" in check_schema({"sku": "A", "price": "4.37"}, SHIM["schemas"]["get_price"])
    assert check_schema({"sku": "A", "price": True}, SHIM["schemas"]["get_price"])  # bool is not a number
    assert "expected array" in check_schema({"text": "[]"}, SHIM["schemas"]["list_notes"])
    kind, reason = classify(SHIM, "get_price", _ok("x") | {"result": {"content": [{"type": "text", "text": "abc"}]}})
    assert kind == "validation" and "not valid JSON" in reason
    assert classify(SHIM, "get_price", {"error": {"code": -32602, "message": "bad"}})[0] == "protocol"
    assert classify(SHIM, "get_price", {"result": {"content": [{"type": "text", "text": "Access Denied"}],
                                                   "isError": True}}) == ("error", "Access Denied")


# ------------------------------------------------------------------------------------------- through the proxy

def _shim_config(tmp_path, **overrides):
    config = {**SHIM, "retry": {"max_retries": 3, "backoff_s": [0.01, 0.02, 0.03]}, **overrides}
    path = tmp_path / "shim.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


class Proxy:
    def __init__(self, tmp_path, faults, shim=None, server="tests.fake_server", seed="dev:1"):
        schedule = tmp_path / "schedule.yaml"
        schedule.write_text(yaml.safe_dump({"seed": seed, "faults": faults}), encoding="utf-8")
        self.log = tmp_path / "proxy.jsonl"
        self.state = tmp_path / "state.json"
        command = [sys.executable, "-m", "mcp_fault_bench", "proxy", "--schedule", str(schedule), "--log", str(self.log)]
        if shim:
            command += ["--shim", str(shim)]
        environment = {**os.environ, "PYTHONPATH": str(ROOT), "CHAOS_STATE_FILE": str(self.state)}
        self.process = subprocess.Popen([*command, "--", sys.executable, "-m", server], cwd=ROOT, env=environment,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        text=True, bufsize=1)
        self.send({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        assert self.read()["id"] == 0

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def call(self, request_id, name, arguments=None):
        self.send({"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                   "params": {"name": name, "arguments": arguments or {}}})

    def read(self, wait=5.0):
        line = self.read_line(wait)
        return json.loads(line) if line is not None else None

    def read_line(self, wait=5.0):
        readable, _, _ = select.select([self.process.stdout], [], [], wait)
        return self.process.stdout.readline() if readable else None

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

    def events(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def shim_events(self):
        return [event for event in self.events() if event.get("layer") == "shim"]


@pytest.fixture
def proxies():
    opened = []
    yield opened
    for proxy in opened:
        if proxy.process.poll() is None:
            proxy.process.kill()
            proxy.process.wait()


def _open(proxies, *args, **kwargs):
    proxy = Proxy(*args, **kwargs)
    proxies.append(proxy)
    return proxy


def _text(response):
    return response["result"]["content"][0]["text"]


def test_retry_recovers_intermittent_error(tmp_path, proxies):
    faults = [{"op": "error", "tools": ["get_price"], "persistence": "transient", "activation_p": 1.0, "max_fires": 2}]
    proxy = _open(proxies, tmp_path, faults, shim=_shim_config(tmp_path))
    proxy.call(1, "get_price", {"sku": "SKU-1"})
    response = proxy.read()
    assert response["id"] == 1 and response["result"]["isError"] is False
    assert json.loads(_text(response)) == {"sku": "SKU-1", "price": 4.37}
    proxy.close()
    (event,) = proxy.shim_events()
    assert event["shim"] | {"reason": None} == {"attempts": 3, "retried": 2, "validation_failures": 0, "timed_out": False,
                                                "final": "ok", "attempt_faults": ["error", "error", None], "reason": None}
    downstream = [e for e in proxy.events() if e.get("layer") != "shim"]
    assert [e["fault"] for e in downstream] == ["error", "error", None]
    assert len({e["downstream_id"] for e in downstream}) == 3  # each retry is a new JSON-RPC id


def test_validation_catches_op2_corruption_and_retries(tmp_path, proxies):
    faults = [{"op": "random_value", "tools": ["get_price"], "persistence": "transient", "activation_p": 1.0,
               "max_fires": 1, "params": {"probability_per_word": 1.0}}]
    proxy = _open(proxies, tmp_path, faults, shim=_shim_config(tmp_path))
    proxy.call(1, "get_price", {"sku": "SKU-1"})
    response = proxy.read()
    assert json.loads(_text(response)) == {"sku": "SKU-1", "price": 4.37}
    proxy.close()
    (event,) = proxy.shim_events()
    assert event["shim"]["attempts"] == 2 and event["shim"]["validation_failures"] == 1
    assert event["shim"]["attempt_faults"] == ["random_value", None]


def test_op3_wrapper_rejected_by_schema_and_value_withheld(tmp_path, proxies):
    faults = [{"op": "wrong_type", "tools": ["get_price"], "persistence": "permanent", "activation_p": 1.0}]
    proxy = _open(proxies, tmp_path, faults, shim=_shim_config(tmp_path))
    proxy.call(1, "get_price", {"sku": "SKU-1"})
    response = proxy.read()
    assert response["result"]["isError"] is True
    text = _text(response)
    assert text.startswith("[resilience-shim] get_price failed after 4 attempts:")
    assert "value is missing required key" in text
    assert "The returned value was withheld because it failed validation." in text
    assert text.endswith("Alternatives: get_price_v2.")
    assert "4.37" not in text
    proxy.close()
    (event,) = proxy.shim_events()
    assert event["shim"]["validation_failures"] == 4 and event["shim"]["final"] == "error"


def test_place_order_is_never_retried(tmp_path, proxies):
    faults = [{"op": "error", "tools": ["place_order"], "persistence": "transient", "activation_p": 1.0, "max_fires": 1}]
    proxy = _open(proxies, tmp_path, faults, shim=_shim_config(tmp_path))
    proxy.call(1, "place_order", {"sku": "SKU-1", "quantity": 2})
    text = _text(proxy.read())
    assert "failed after 1 attempt:" in text
    assert "place_order is not idempotent and was not retried: the side effect may have happened" in text
    assert "check list_orders before retrying" in text
    proxy.call(2, "place_order", {"sku": "SKU-1", "quantity": 2})  # the agent's own retry goes through
    assert json.loads(_text(proxy.read())) == {"sku": "SKU-1", "quantity": 2}
    proxy.close()
    assert [event["shim"]["attempts"] for event in proxy.shim_events()] == [1, 1]
    # Rule-mode OP4 replaces the response after the server ran: the first order did happen, as the note warns.
    assert json.loads(proxy.state.read_text())["orders"] == [{"sku": "SKU-1", "quantity": 2}] * 2


def test_timeout_returns_error_and_drops_the_late_response(tmp_path, proxies):
    proxy = _open(proxies, tmp_path, [], shim=_shim_config(tmp_path, attempt_timeout_s=0.3))
    started = time.monotonic()
    proxy.call(1, "slow", {"seconds": 0.8})
    response = proxy.read()
    assert time.monotonic() - started < 0.7
    assert response["id"] == 1 and response["result"]["isError"] is True
    assert _text(response) == "[resilience-shim] slow did not respond within 0.3 s (no retry)."
    time.sleep(0.8)  # the late response arrives at the shim now and must not reach the agent
    proxy.call(2, "get_price", {"sku": "SKU-2"})
    assert proxy.read()["id"] == 2
    assert proxy.read(wait=0.3) is None
    proxy.close()
    first = proxy.shim_events()[0]
    assert first["shim"]["timed_out"] and first["shim"]["attempts"] == 1 and first["shim"]["retried"] == 0


def test_dropped_place_order_times_out_with_side_effect_note(tmp_path, proxies):
    faults = [{"op": "drop_call", "tools": ["place_order"], "persistence": "transient", "activation_p": 1.0}]
    proxy = _open(proxies, tmp_path, faults, shim=_shim_config(tmp_path, attempt_timeout_s=0.3))
    proxy.call(1, "place_order", {"sku": "SKU-3", "quantity": 1})
    text = _text(proxy.read())
    assert text.startswith("[resilience-shim] place_order did not respond within 0.3 s (no retry).")
    assert "side effect may have happened" in text
    proxy.close()
    assert json.loads(proxy.state.read_text())["orders"] == [{"sku": "SKU-3", "quantity": 1}]


def test_fallback_text_on_error(tmp_path, proxies):
    faults = [{"op": "error", "tools": ["get_price"], "persistence": "permanent", "activation_p": 1.0}]
    proxy = _open(proxies, tmp_path, faults, shim=_shim_config(tmp_path))
    proxy.call(1, "get_price", {"sku": "SKU-1"})
    text = _text(proxy.read())
    assert text == ("[resilience-shim] get_price failed after 4 attempts: Access Denied to: tool "
                    "(service unavailable 503). Alternatives: get_price_v2.")
    proxy.close()


def test_parallel_calls_get_exactly_one_response_each(tmp_path, proxies):
    faults = [{"op": "error", "tools": ["get_price_v2"], "persistence": "transient", "activation_p": 1.0, "max_fires": 3}]
    proxy = _open(proxies, tmp_path, faults, shim=_shim_config(tmp_path, attempt_timeout_s=2))
    proxy.call("a", "slow", {"seconds": 0.4})
    proxy.call("b", "get_price_v2", {"sku": "SKU-9"})
    proxy.call("c", "get_price", {"sku": "SKU-8"})
    proxy.send({"jsonrpc": "2.0", "id": "d", "method": "ping"})
    responses = [proxy.read() for _ in range(4)]
    assert sorted(response["id"] for response in responses) == ["a", "b", "c", "d"]
    assert proxy.read(wait=0.6) is None  # no duplicates, no leaked downstream ids
    by_id = {response["id"]: response for response in responses}
    assert json.loads(_text(by_id["b"])) == {"sku": "SKU-9", "price": 4.37}
    assert json.loads(_text(by_id["a"])) == {"slept": 0.4}
    proxy.close()
    assert sorted(event["shim"]["attempts"] for event in proxy.shim_events()) == [1, 1, 4]


def test_shim_on_paper_profile_answers_every_request_once(tmp_path):
    config = _shim_config(tmp_path, attempt_timeout_s=1)
    for schedule, seed, target, server, calls in SESSIONS[:3]:
        session = run_session(schedule, seed, target, server, calls, shim=config, wait=3)
        for lines, expected_id in zip(session["stdout"][3:], range(10, 10 + len(calls))):
            assert [json.loads(line)["id"] for line in lines] == [expected_id]
        shim_events = [event for event in session["log"] if event.get("layer") == "shim"]
        assert len(shim_events) == len(calls)


def test_shim_off_is_byte_identical_to_the_pre_shim_proxy():
    golden = json.loads((ROOT / "tests" / "golden" / "shim_off.json").read_text(encoding="utf-8"))
    assert len(golden) == len(SESSIONS)
    for session, expected in zip(SESSIONS, golden):
        assert run_session(*session) == expected
