"""Paper-faithful profile-draw engine: draw/hold semantics, seeding, scope, and the paper operators."""

from __future__ import annotations

import json
import os
import select
import string
import subprocess
import sys
import time
from pathlib import Path

import yaml

from mcp_fault_bench.proxy import ProfileDrawEngine, _mutate, load_schedule

ROOT = Path(__file__).resolve().parents[1]
PAPER = load_schedule(str(ROOT / "profiles" / "paper_opp.yaml"))


def _schedule(*entries, **extra):
    return {"kind": "profile_draw", "seed": 7, "entries": list(entries), **extra}


def _entry(op="error", persistence="permanent", weight=1.0, **values):
    return {"op": op, "persistence": persistence, "weight": weight, "paper_type": "OP4_errorMessage",
            "params": {}, **values}


def _trace(engine, tools):
    return [(d["draw_index"], d["entry"]["label"], d["fired"]) if d else None for d in map(engine.choose, tools)]


def test_same_seed_same_draws_and_fired_events():
    tools = ["get_price", "get_stock", "get_note"] * 20
    first = _trace(ProfileDrawEngine(PAPER, seed="42:price_total:1"), tools)
    assert first == _trace(ProfileDrawEngine(PAPER, seed="42:price_total:1"), tools)
    traces = {tuple(_trace(ProfileDrawEngine(PAPER, seed=f"42:t:{rep}"), tools)) for rep in range(20)}
    assert len(traces) > 1


def test_draw_frequencies_match_weights():
    draws = 20_000
    counts: dict[str, int] = {}
    for index in range(draws):
        label = ProfileDrawEngine(PAPER, seed=f"freq:{index}").choose("tool")["entry"]["label"]
        counts[label] = counts.get(label, 0) + 1
    total_weight = sum(entry["weight"] for entry in PAPER["entries"])
    assert abs(counts["OP4/permanent"] / draws - 0.6565 / total_weight) < 0.02
    assert abs(counts.get("OP2/permanent", 0) / draws - 0.1254 / total_weight) < 0.02
    permanent = sum(value for key, value in counts.items() if key.endswith("/permanent"))
    assert abs(permanent / draws - 0.913) < 0.02
    assert "OP1/transient" not in counts  # weight 0.0 is never drawn


def test_permanent_entry_is_held_and_fires_every_call():
    engine = ProfileDrawEngine(_schedule(_entry(), _entry(op="delay", weight=0.0)))
    decisions = [engine.choose("tool") for _ in range(12)]
    assert all(d["draw_index"] == 0 and d["fired"] and d["op"] == "error" for d in decisions)
    assert engine.draws == 1


def test_transient_entry_redraws_on_next_call():
    engine = ProfileDrawEngine(_schedule(_entry(persistence="transient", activation_p=1.0)))
    decisions = [engine.choose("tool") for _ in range(5)]
    assert [d["draw_index"] for d in decisions] == [0, 1, 2, 3, 4]
    assert all(d["fired"] for d in decisions)


def test_intermittent_release_applies_to_releasing_call_then_redraws():
    always = ProfileDrawEngine(_schedule(_entry(persistence="intermittent", activation_p=1.0, deactivation_p=1.0)))
    # call 0 draws; call 1 releases but still uses draw 0; call 2 draws again.
    assert [always.choose("tool")["draw_index"] for _ in range(5)] == [0, 0, 1, 1, 2]
    never = ProfileDrawEngine(_schedule(_entry(persistence="intermittent", activation_p=1.0, deactivation_p=0.0)))
    assert {never.choose("tool")["draw_index"] for _ in range(30)} == {0}
    quiet = ProfileDrawEngine(_schedule(_entry(persistence="intermittent", activation_p=0.0, deactivation_p=0.0)))
    assert not any(quiet.choose("tool")["fired"] for _ in range(30))
    sometimes = ProfileDrawEngine(_schedule(_entry(persistence="intermittent", activation_p=0.5, deactivation_p=0.0)))
    fired = [sometimes.choose("tool")["fired"] for _ in range(200)]
    assert 60 < sum(fired) < 140


def test_scope_filters_tools_and_only_matching_calls_advance_state():
    schedule = _schedule(_entry(persistence="transient", activation_p=1.0), scope="tools", tools=["get_price"])
    engine = ProfileDrawEngine(schedule)
    assert engine.choose("get_stock") is None
    decision = engine.choose("get_price")
    assert decision["call_index"] == 0 and decision["draw_index"] == 0
    targeted = ProfileDrawEngine(_schedule(_entry()), target="put_note")
    assert targeted.choose("get_note") is None and targeted.choose("put_note")["fired"]


def test_two_proxies_with_the_same_seed_draw_the_same_first_entry():
    for rep in range(50):
        notes = ProfileDrawEngine(PAPER, seed=f"42:cross_server_total:{rep}")
        inventory = ProfileDrawEngine(PAPER, seed=f"42:cross_server_total:{rep}")
        assert notes.choose("get_note")["entry"] == inventory.choose("get_price")["entry"]


def _response(text):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}], "isError": False}}


def test_paper_small_delta_changes_at_most_one_letter_per_word():
    text = "alpha beta gamma delta epsilon zeta eta theta"
    out = _mutate(_response(text), {"op": "small_delta", "params": {"probability_per_word": 1.0, "_rng_seed": "s"}})
    words, mutated = text.split(), out["result"]["content"][0]["text"].split()
    assert len(words) == len(mutated)
    for before, after in zip(words, mutated):
        assert len(before) == len(after)
        diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        assert len(diffs) <= 1 and all(after[i] in string.ascii_letters for i in diffs)
    untouched = _mutate(_response(text), {"op": "small_delta", "params": {"probability_per_word": 0.0, "_rng_seed": "s"}})
    assert untouched["result"]["content"][0]["text"] == text


def test_paper_random_value_replaces_words_with_letters_of_same_length():
    text = '{"sku": "SKU-639", "price": 7.19}'
    out = _mutate(_response(text), {"op": "random_value", "params": {"probability_per_word": 1.0, "_rng_seed": "s"}})
    mutated = out["result"]["content"][0]["text"].split()
    assert [len(word) for word in mutated] == [len(word) for word in text.split()]
    assert all(set(word) <= set(string.ascii_letters) for word in mutated)
    partial = _mutate(_response(" ".join(["w"] * 2000)),
                      {"op": "random_value", "params": {"probability_per_word": 0.35, "_rng_seed": "s"}})
    changed = sum(word != "w" for word in partial["result"]["content"][0]["text"].split())
    assert 0.30 < changed / 2000 < 0.40  # a replaced one-letter word is "w" again with p=1/52


def test_paper_wrong_type_wraps_text():
    out = _mutate(_response('{"price": 7.19}'), {"op": "wrong_type", "params": {}})
    assert json.loads(out["result"]["content"][0]["text"]) == {"text": '{"price": 7.19}'}


def _proxy(tmp_path, server, entry, state=None, seed="42", target=None):
    schedule = tmp_path / "profile.yaml"
    schedule.write_text(yaml.safe_dump(_schedule(entry)))
    log = tmp_path / "proxy.jsonl"
    environment = {**os.environ, "PYTHONPATH": str(ROOT)}
    if state:
        environment["CHAOS_STATE_FILE"] = str(state)
    command = [sys.executable, "-m", "mcp_fault_bench", "proxy", "--schedule", str(schedule), "--seed", seed, "--log", str(log)]
    if target:
        command += ["--target", target]
    process = subprocess.Popen([*command, "--", sys.executable, "-m", f"servers.{server}"], cwd=ROOT, env=environment,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    _send(process, {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    process.stdout.readline()
    return process, log


def _send(process, message):
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()


def _call(process, request_id, name, arguments, wait=5.0):
    _send(process, {"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                    "params": {"name": name, "arguments": arguments}})
    readable, _, _ = select.select([process.stdout], [], [], wait)
    return json.loads(process.stdout.readline()) if readable else None


def _stop(process):
    process.terminate()
    process.wait(timeout=5)


def test_paper_error_returns_access_denied_without_calling_server(tmp_path):
    state = tmp_path / "notes.json"
    process, log = _proxy(tmp_path, "notes", _entry(), state=state)
    try:
        response = _call(process, 1, "put_note", {"key": "k", "value": "v"})
        assert response["result"] == {"content": [{"type": "text", "text": "Access Denied to: put_note"}], "isError": True}
        assert not state.exists()  # like the reference ToolError, the server never sees the call
    finally:
        _stop(process)
    event = json.loads(log.read_text().splitlines()[0])
    assert event["fault"] == "error" and event["fired"] is True and event["draw_index"] == 0
    assert event["entry"] == {"paper_type": "OP4_errorMessage", "persistence": "permanent", "label": "OP4/permanent"}


def test_paper_drop_call_forwards_but_never_answers(tmp_path):
    state = tmp_path / "notes.json"
    process, log = _proxy(tmp_path, "notes", _entry(op="drop_call", paper_type="OP6_dropCall"), state=state)
    try:
        assert _call(process, 1, "put_note", {"key": "k", "value": "v"}, wait=0.5) is None
        assert json.loads(state.read_text()) == {"k": "v"}  # side effect happened
    finally:
        _stop(process)
    event = json.loads(log.read_text().splitlines()[0])
    assert event["fault"] == "drop_call" and event["outcome"] == "dropped"


def test_paper_delay_sleeps_then_forwards_without_blocking_other_traffic(tmp_path):
    entry = _entry(op="delay", paper_type="OP5_delay", persistence="transient", activation_p=1.0, params={"seconds": 0.4})
    process, log = _proxy(tmp_path, "notes", entry, target="get_note")
    try:
        started = time.monotonic()
        _send(process, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "get_note", "arguments": {"key": "k"}}})
        listed = _call(process, 2, "list_notes", {})  # out of scope: answered while the delay runs
        assert listed["id"] == 2 and time.monotonic() - started < 0.35
        delayed = json.loads(process.stdout.readline())
        assert delayed["id"] == 1 and time.monotonic() - started >= 0.4
    finally:
        _stop(process)
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert {event["tool"]: event["fired"] for event in events} == {"list_notes": False, "get_note": True}
    assert next(event for event in events if event["tool"] == "list_notes")["draw_index"] is None


def test_unfired_draws_are_logged(tmp_path):
    entry = _entry(op="error", persistence="intermittent", activation_p=0.0, deactivation_p=0.0)
    process, log = _proxy(tmp_path, "notes", entry)
    try:
        assert _call(process, 1, "get_note", {"key": "k"})["result"]["isError"] is False
    finally:
        _stop(process)
    event = json.loads(log.read_text().splitlines()[0])
    assert event["fired"] is False and event["fault"] is None and event["draw_index"] == 0
    assert event["entry"]["label"] == "OP4/intermittent"
