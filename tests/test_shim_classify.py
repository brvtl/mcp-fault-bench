"""Resilience shim, classify mode (profiles/shim.yaml, pre-registered in docs/preregistration-shim.md).

Seeds are dev strings ("dev:<n>") only.
"""

from __future__ import annotations

import json
import time

import yaml

from mcp_fault_bench.shim import NO_FALLBACK, Shim, load_shim_config
from tests.test_shim import ROOT, _open, _text, proxies  # noqa: F401  (pytest fixture)

SHIM = load_shim_config(str(ROOT / "profiles" / "shim.yaml"))
DENIED = "Access Denied to: tool (service unavailable 503)"


def _config(tmp_path, **overrides):
    path = tmp_path / "shim.yaml"
    path.write_text(yaml.safe_dump({**SHIM, **overrides}), encoding="utf-8")
    return path


def _denied(*tools, **extra):
    return [{"op": "error", "tools": [tool], "persistence": "permanent", "activation_p": 1.0, **extra} for tool in tools]


def _permanent(tool, error, tail):
    return f"PERMANENT: {tool} failed ({error}). Do not retry {tool}; it will not recover in this session. {tail}"


def test_profile_is_classify_mode_without_retries_or_validation():
    assert SHIM["mode"] == "classify" and SHIM["retry"]["max_retries"] == 0
    assert SHIM["validate"] != "json" and SHIM["attempt_timeout_s"] == 35
    assert load_shim_config(str(ROOT / "profiles" / "shim_retry.yaml"))["mode"] == "retry"


def test_access_denied_is_permanent_and_names_the_fallback(tmp_path, proxies):
    faults = _denied("get_price") + _denied("get_price_v2", params={"style": "jsonrpc", "message": "Forbidden"})
    proxy = _open(proxies, tmp_path, faults, shim=_config(tmp_path))
    proxy.call(1, "get_price", {"sku": "SKU-1"})
    response = proxy.read()
    assert response["id"] == 1 and response["result"]["isError"] is True
    assert _text(response) == _permanent("get_price", DENIED, "Use fallback tool get_price_v2 instead.")
    proxy.call("x", "get_price_v2", {"sku": "SKU-1"})  # JSON-RPC error: isError result with the same id
    response = proxy.read()
    assert response["id"] == "x" and response["result"]["isError"] is True and "error" not in response
    assert _text(response).startswith("PERMANENT: get_price_v2 failed (Forbidden).")
    proxy.close()
    first, second = proxy.shim_events()
    assert (first["shim_class"], first["fallback_named"]) == ("permanent", ["get_price_v2"])
    assert (second["shim_class"], second["fallback_named"]) == ("permanent", None)


def test_fallback_is_skipped_once_it_is_also_permanent(tmp_path, proxies):
    proxy = _open(proxies, tmp_path, _denied("get_price", "get_price_v2", "get_note", "search_notes"),
                  shim=_config(tmp_path))
    calls = [("get_note", "Use fallback tool search_notes or list_notes instead."),
             ("search_notes", NO_FALLBACK),  # its only fallback, get_note, is already PERMANENT
             ("get_note", "Use fallback tool list_notes instead."),
             ("get_price", "Use fallback tool get_price_v2 instead."),
             ("get_price_v2", NO_FALLBACK),
             ("get_price", NO_FALLBACK)]
    for request_id, (tool, tail) in enumerate(calls, 1):
        proxy.call(request_id, tool, {"sku": "SKU-1", "key": "k", "query": "q"})
        assert _text(proxy.read()) == _permanent(tool, DENIED, tail), tool
    proxy.close()
    assert [event["fallback_named"] for event in proxy.shim_events()] == [
        ["search_notes", "list_notes"], None, ["list_notes"], ["get_price_v2"], None, None]


def test_tool_without_fallback_gets_the_no_alternative_text(tmp_path, proxies):
    proxy = _open(proxies, tmp_path, _denied("get_stock"), shim=_config(tmp_path))
    proxy.call(1, "get_stock", {"sku": "SKU-1"})
    assert _text(proxy.read()) == _permanent("get_stock", DENIED, NO_FALLBACK)
    proxy.close()


def test_place_order_gets_the_list_orders_hint(tmp_path, proxies):
    proxy = _open(proxies, tmp_path, _denied("place_order"), shim=_config(tmp_path))
    proxy.call(1, "place_order", {"sku": "SKU-1", "quantity": 2})
    assert _text(proxy.read()) == _permanent(
        "place_order", DENIED, NO_FALLBACK + " The order may or may not have been placed; check list_orders before "
                                             "ordering again.")
    proxy.close()


def test_timeout_is_unresponsive_and_the_late_response_is_dropped(tmp_path, proxies):
    proxy = _open(proxies, tmp_path, [], shim=_config(tmp_path, attempt_timeout_s=1))
    started = time.monotonic()
    proxy.call(1, "slow", {"seconds": 2.0})
    response = proxy.read()
    assert time.monotonic() - started < 1.8
    assert response["id"] == 1 and response["result"]["isError"] is True
    assert _text(response) == _permanent("slow", "UNRESPONSIVE: no response within 1 s", NO_FALLBACK)
    time.sleep(1.2)  # the late response arrives at the shim now and must not reach the agent
    proxy.call(2, "get_price", {"sku": "SKU-2"})
    assert proxy.read()["id"] == 2
    assert proxy.read(wait=0.3) is None
    proxy.close()
    first = proxy.shim_events()[0]
    assert first["shim_class"] == "unresponsive" and first["shim"]["timed_out"] is True


def test_second_consecutive_other_error_is_permanent_and_a_success_resets(tmp_path, proxies):
    # fake_server's slow tool returns isError "Error: could not convert string to float: 'x'" for a bad argument.
    proxy = _open(proxies, tmp_path, [], shim=_config(tmp_path))
    raw = []
    for request_id, seconds in enumerate(("x", "x", 0, "x"), 1):
        proxy.call(request_id, "slow", {"seconds": seconds})
        raw.append(proxy.read_line())
    proxy.close()
    first, second, third, fourth = map(json.loads, raw)
    error = "Error: could not convert string to float: 'x'"
    assert first["result"] == {"content": [{"type": "text", "text": error}], "isError": True}  # passed through
    assert _text(second) == _permanent("slow", error, NO_FALLBACK)
    assert third["result"]["isError"] is False
    assert fourth["result"] == first["result"]  # the success reset the streak
    assert [event["shim_class"] for event in proxy.shim_events()] == ["pass", "permanent", "pass", "pass"]


def test_successful_response_is_byte_identical_to_the_shim_off_proxy(tmp_path, proxies):
    lines = []
    for shim in (None, _config(tmp_path)):
        proxy = _open(proxies, tmp_path, [], shim=shim)
        proxy.call(7, "get_price", {"sku": "SKU-7"})
        lines.append(proxy.read_line())
        proxy.close()
    assert lines[0] == lines[1]
    (event,) = proxy.shim_events()
    assert (event["shim_class"], event["fallback_named"]) == ("pass", None)


def test_exactly_one_downstream_call_per_agent_call(tmp_path, proxies):
    faults = [{"op": "error", "tools": ["get_price"], "persistence": "transient", "activation_p": 1.0, "max_fires": 1},
              {"op": "error", "tools": ["get_price_v2"], "persistence": "transient", "activation_p": 1.0, "max_fires": 2,
               "params": {"message": "Internal error"}}]
    proxy = _open(proxies, tmp_path, faults, shim=_config(tmp_path))
    calls = ["get_price", "get_price", "get_price_v2", "get_price_v2", "get_price_v2", "place_order"]
    for request_id, tool in enumerate(calls, 1):
        proxy.call(request_id, tool, {"sku": "SKU-1", "quantity": 1})
        assert proxy.read()["id"] == request_id
    proxy.close()
    downstream = [event for event in proxy.events() if event.get("layer") != "shim"]
    assert [event["tool"] for event in downstream] == calls
    assert [event["fault"] for event in downstream] == ["error", None, "error", "error", None, None]
    assert [event["shim"]["attempts"] for event in proxy.shim_events()] == [1] * len(calls)
    assert [event["shim_class"] for event in proxy.shim_events()] == [
        "permanent", "pass", "pass", "permanent", "pass", "pass"]
    assert json.loads((tmp_path / "state.json").read_text())["orders"] == [{"sku": "SKU-1", "quantity": 1}]


def test_protocol_errors_pass_through_untouched():
    sent, answers, logged = [], [], []
    shim = Shim(SHIM, sent.append, answers.append, logged.append, "run")
    error = {"code": -32602, "message": "Invalid params: not found"}  # matches the pattern, but is a client mistake
    shim.from_client(json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                 "params": {"name": "get_price", "arguments": {}}}))
    deadline = time.monotonic() + 5
    while not sent and time.monotonic() < deadline:
        time.sleep(0.01)
    shim.from_downstream({"jsonrpc": "2.0", "id": json.loads(sent[0])["id"], "error": error})
    shim.close()
    assert answers == [{"jsonrpc": "2.0", "id": 3, "error": error}]
    assert logged[0]["shim_class"] == "pass"
