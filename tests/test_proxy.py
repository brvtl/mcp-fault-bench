"""Unit and subprocess integration tests for fault schedules and MCP proxy behavior."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import yaml

from mcp_fault_bench.profile import MAP, convert
from mcp_fault_bench.proxy import OPS, FaultEngine, _drift_tools, _mutate

ROOT = Path(__file__).resolve().parents[1]


def _rule(persistence: str = "transient", **values):
    return {"op": "error", "tools": ["widget"], "persistence": persistence, **values}


def test_paper_persistence_types():
    permanent = FaultEngine({"seed": 9, "faults": [_rule("permanent", activation_p=1)]})
    assert all(permanent.choose("widget") is not None for _ in range(8))

    transient = FaultEngine({"seed": 9, "faults": [_rule("transient", activation_p=1)]})
    assert transient.choose("widget") is not None
    assert all(transient.choose("widget") is None for _ in range(7))

    intermittent = FaultEngine({"seed": 9, "faults": [_rule("intermittent", activation_p=1, deactivation_p=0)]})
    assert all(intermittent.choose("widget") is not None for _ in range(8))


def test_after_calls_and_max_fires():
    engine = FaultEngine({"seed": 42, "faults": [_rule("transient", activation_p=1, after_calls=2, max_fires=1)]})
    assert engine.choose("widget") is None
    assert engine.choose("widget") is None
    assert engine.choose("widget") is not None
    assert engine.choose("widget") is None


def test_same_seed_repeats_fault_sequence_and_other_seed_differs():
    schedule = {"seed": 42, "faults": [_rule("transient", activation_p=0.5, max_fires=20)]}

    def sequence(seed):
        schedule["seed"] = seed
        engine = FaultEngine(schedule)
        return [engine.choose("widget") is not None for _ in range(30)]

    first = sequence(42)
    assert first == sequence(42)
    assert first != sequence(43)


def test_every_operator_has_expected_mapping_and_mutation():
    baseline = {"jsonrpc": "2.0", "id": 7, "result": {
        "content": [{"type": "text", "text": "SKU-731 costs 12.50"}], "isError": False}}
    for operation in ("small_delta", "random_value", "wrong_type", "truncate", "error"):
        result = _mutate(json.loads(json.dumps(baseline)), {"op": operation,
                         "params": {"percent": 40, "_rng_seed": "stable"}})
        assert result != baseline
    rpc_error = _mutate(json.loads(json.dumps(baseline)), {"op": "error", "params": {"style": "jsonrpc"}})
    assert rpc_error["error"]["code"] == -32003
    assert set(OPS) == {"small_delta", "random_value", "wrong_type", "error", "delay", "timeout",
                        "drop_call", "malformed_json", "truncate", "schema_drift"}
    for operation in OPS:
        engine = FaultEngine({"seed": 4, "faults": [{"op": operation, "tools": ["widget"],
                                                         "persistence": "transient", "activation_p": 1}]})
        assert engine.choose("widget")[1]["op"] == operation


def test_schema_drift_changes_listing_and_rejects_old_argument():
    listing = {"result": {"tools": [{"name": "place_order", "inputSchema": {
        "type": "object", "properties": {"quantity": {"type": "integer"}}, "required": ["quantity"]}}]}}
    drift = {"op": "schema_drift", "tools": ["place_order"], "params": {"rename": "quantity", "to": "count"}}
    changed = _drift_tools(listing, [drift])
    schema = changed["result"]["tools"][0]["inputSchema"]
    assert "count" in schema["properties"]
    assert schema["required"] == ["count"]
    engine = FaultEngine({"seed": 1, "faults": [{**drift, "persistence": "transient", "activation_p": 1}]})
    assert engine.choose("place_order")[1]["op"] == "schema_drift"


def test_delay_is_real_and_timeout_and_drop_are_selected():
    started = time.monotonic()
    assert FaultEngine({"seed": 1, "faults": [{"op": "delay", "tools": ["widget"],
        "persistence": "transient", "activation_p": 1, "params": {"seconds": 0.02}}]}).choose("widget")
    time.sleep(0.02)
    assert time.monotonic() - started >= 0.02
    for operation in ("timeout", "drop_call"):
        selected = FaultEngine({"seed": 1, "faults": [{"op": operation, "tools": ["widget"],
            "persistence": "transient", "activation_p": 1}]}).choose("widget")
        assert selected[1]["op"] == operation


def test_paper_profile_conversion_keeps_all_entries_and_weights(tmp_path):
    source = ROOT / "third_party" / "mcp-injector" / "fault_mode_1.json"
    target, scoped = tmp_path / "paper.yaml", tmp_path / "scoped.yaml"
    convert(str(source), str(target), str(scoped))
    raw = json.loads(source.read_text())["fault_mode"]
    converted = yaml.safe_load(target.read_text())
    assert converted["kind"] == "profile_draw" and converted["scope"] == "global"
    assert len(converted["entries"]) == len(raw) == 18
    for row, entry in zip(raw, converted["entries"]):
        assert entry["weight"] == row["probability"]
        assert entry["paper_type"] == row["type"] and entry["op"] == MAP[row["type"]]
        assert entry["persistence"] == row["persistence"]["type"].lower()
        if entry["persistence"] == "intermittent":
            assert entry["activation_p"] == row["persistence"]["activation_p"]
            assert entry["deactivation_p"] == row["persistence"]["deactivation_p"]
    assert converted["entries"][0]["params"] == {"seconds": 30}
    assert "CC-BY-4.0" in target.read_text()
    assert yaml.safe_load(scoped.read_text())["scope"] == "tools"
    # The shipped profiles are exactly what the converter produces.
    assert (ROOT / "profiles" / "paper_opp.yaml").read_text() == target.read_text().replace(str(source), "third_party/mcp-injector/fault_mode_1.json")


def _rpc(process, request):
    assert process.stdin and process.stdout
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return line


def _notify(process, notification):
    assert process.stdin
    process.stdin.write(json.dumps(notification) + "\n")
    process.stdin.flush()


def _proxy(tmp_path, server, faults):
    schedule = tmp_path / f"{server}.yaml"
    schedule.write_text(yaml.safe_dump({"seed": 42, "faults": faults}))
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    return subprocess.Popen([sys.executable, "-m", "mcp_fault_bench", "proxy", "--schedule", str(schedule), "--",
                             sys.executable, "-m", f"servers.{server}"], cwd=ROOT, env=environment,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)


def test_malformed_json_is_followed_by_valid_error_and_connection_survives(tmp_path):
    process = _proxy(tmp_path, "notes", [{"op": "malformed_json", "tools": ["get_note"],
        "persistence": "transient", "activation_p": 1, "max_fires": 1}])
    try:
        assert _rpc(process, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})["id"] == 1
        _notify(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        malformed = _rpc(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                   "params": {"name": "get_note", "arguments": {"key": "absent"}}})
        assert isinstance(malformed, str)
        assert json.loads(process.stdout.readline())["error"]["code"] == -32004
        recovered = _rpc(process, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                   "params": {"name": "get_note", "arguments": {"key": "absent"}}})
        assert recovered["id"] == 3
        assert recovered["result"]["isError"] is False
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_scripted_client_through_proxy_against_both_toy_servers(tmp_path):
    for server in ("inventory", "notes"):
        process = _proxy(tmp_path, server, [])
        try:
            initialized = _rpc(process, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                         "params": {"protocolVersion": "2025-06-18"}})
            assert initialized["result"]["protocolVersion"] == "2025-06-18"
            _notify(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            tools = _rpc(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            assert tools["result"]["tools"]
            if server == "inventory":
                request = {"name": "get_price_v2", "arguments": {"sku": "SKU-731"}}
                text = _rpc(process, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": request})
                assert json.loads(text["result"]["content"][0]["text"])["price"] == 4.37
            else:
                put = {"name": "put_note", "arguments": {"key": "test", "value": "hello"}}
                assert _rpc(process, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": put})["id"] == 3
                get = {"name": "get_note", "arguments": {"key": "test"}}
                value = _rpc(process, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": get})
                assert json.loads(value["result"]["content"][0]["text"])["value"] == "hello"
        finally:
            process.terminate()
            process.wait(timeout=5)


def test_schema_drift_is_advertised_and_old_parameter_is_rejected(tmp_path):
    process = _proxy(tmp_path, "inventory", [{"op": "schema_drift", "tools": ["place_order"],
        "persistence": "transient", "activation_p": 1, "max_fires": 1,
        "params": {"rename": "quantity", "to": "count"}}])
    try:
        _rpc(process, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        _notify(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        listing = _rpc(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        schema = next(tool["inputSchema"] for tool in listing["result"]["tools"] if tool["name"] == "place_order")
        assert "count" in schema["properties"] and "quantity" not in schema["properties"]
        # The advertised argument is accepted and translated to the toy server schema.
        accepted = _rpc(process, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "place_order", "arguments": {"sku": "SKU-731", "count": 1}}})
        assert accepted["result"]["isError"] is False
        rejected = _rpc(process, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "place_order", "arguments": {"sku": "SKU-731", "quantity": 1}}})
        assert rejected["error"]["code"] == -32602
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_delay_timeout_and_drop_call_through_proxy(tmp_path):
    delay_process = _proxy(tmp_path, "notes", [{"op": "delay", "tools": ["get_note"],
        "persistence": "transient", "activation_p": 1, "params": {"seconds": 0.08}}])
    try:
        _rpc(delay_process, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        started = time.monotonic()
        _rpc(delay_process, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "get_note", "arguments": {"key": "missing"}}})
        assert time.monotonic() - started >= 0.07
    finally:
        delay_process.terminate()
        delay_process.wait(timeout=5)

    for operation in ("timeout", "drop_call"):
        params = {"seconds": 0.04} if operation == "timeout" else {}
        process = _proxy(tmp_path, "notes", [{"op": operation, "tools": ["get_note"],
            "persistence": "transient", "activation_p": 1, "params": params}])
        try:
            _rpc(process, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
            _notify(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "get_note", "arguments": {"key": "dropped"}}}) + "\n")
            process.stdin.flush()
            readable, _, _ = select.select([process.stdout], [], [], 0.15)
            assert not readable
        finally:
            process.terminate()
            process.wait(timeout=5)
