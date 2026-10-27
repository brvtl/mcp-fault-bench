"""Arena grading, stream-json parsing, run classification and summary tests."""

import json

from bench import arena
from bench.arena import (call_stats, claude_command, final_answer, grade, parse_stream, pick_target, proxy_draws,
                         retry_counts, target_behaviour,
                         run_seed, score_run, summarize, wilson)


def test_grade_answer_and_persisted_state(tmp_path):
    assert grade({"grade": {"type": "answer_number", "value": 7.4}}, "7.40", {})
    assert grade({"grade": {"type": "answer_number", "value": 1234.5}}, "$1,234.50", {})
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"orders": [{"sku": "SKU-562", "quantity": 3}]}))
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"budget-order": "SKU-562 x3"}))
    states = {"inventory": str(inventory), "notes": str(notes)}
    exact = {"type": "orders_exact", "orders": [{"sku": "SKU-562", "quantity": 3}]}
    note = {"type": "note", "key": "budget-order", "value": "SKU-562 x3"}
    assert grade({"grade": exact}, "", states)
    assert grade({"grade": {"type": "all", "checks": [exact, note]}}, "", states)
    inventory.write_text(json.dumps({"orders": [{"sku": "SKU-562", "quantity": 3}, {"sku": "SKU-731", "quantity": 1}]}))
    assert not grade({"grade": exact}, "", states)  # extra orders fail
    assert not grade({"grade": exact}, "", {"inventory": str(tmp_path / "missing.json")})


def test_final_answer_takes_last_final_line():
    assert final_answer("FINAL: 1\nthinking\n**FINAL: `56.55`**") == "56.55"
    assert final_answer("no answer") == ""


def _stream(tool_results, result=True, servers=("inventory",)):
    events = [{"type": "system", "subtype": "init", "model": "claude-haiku-5-5",
               "tools": [f"mcp__{server}__get_price" for server in servers],
               "mcp_servers": [{"name": server, "status": "connected"} for server in servers]}]
    for index, (name, is_error) in enumerate(tool_results):
        events.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{index}", "name": name, "input": {}}]}})
        events.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{index}", "is_error": is_error, "content": "x"}]}})
    if result:
        events.append({"type": "result", "subtype": "success", "is_error": False, "num_turns": 3,
                       "duration_ms": 1000, "total_cost_usd": 0.01, "result": "done\nFINAL: 56.55",
                       "modelUsage": {"claude-haiku-5-5": {"inputTokens": 10, "outputTokens": 5, "costUSD": 0.01}}})
    return events


def test_parse_stream_and_call_stats_count_retries_fallbacks_and_builtins():
    events = _stream([("mcp__inventory__get_price", True), ("mcp__inventory__get_price_v2", False),
                      ("mcp__inventory__get_stock", False), ("mcp__inventory__get_stock", False),
                      ("mcp__notes__get_note", True), ("mcp__notes__search_notes", False), ("Bash", False)])
    parsed = parse_stream(events)
    assert parsed["init"]["model"] == "claude-haiku-5-5" and parsed["result"]["num_turns"] == 3
    assert [call["tool"] for call in parsed["calls"]][:2] == ["get_price", "get_price_v2"]
    # Switching tools is a fallback, not a retry; the repeated get_stock had no error result, so it is a repeat only.
    proxy = [{"tool": "get_price", "fault": "error"}, {"tool": "get_stock", "fault": "random_value"},
             {"tool": "get_stock", "fault": None}]
    stats = call_stats(parsed["calls"], proxy)
    assert stats["tool_calls"] == 6 and stats["errored_tool_calls"] == 2
    assert stats["retries"] == 0 and stats["same_args_repeats"] == 1 and stats["used_fallback_tool"]
    assert stats["builtin_tool_usage"] and stats["builtin_tools"] == ["Bash"]
    clean = call_stats(parse_stream(_stream([("mcp__inventory__get_price_v2", False)]))["calls"], [])
    assert not clean["used_fallback_tool"] and clean["retries"] == 0


def _batch(*turns):
    """Stream where each turn is a parallel batch of (id, tool, args, is_error) calls, results after the batch."""
    events = []
    for turn in turns:
        events.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": ident, "name": f"mcp__inventory__{tool}", "input": args}
            for ident, tool, args, _ in turn]}})
        events.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": ident, "is_error": error, "content": "x"}
            for ident, _, _, error in turn]}})
    return parse_stream(events)["calls"]


def test_retries_count_only_same_arguments_after_the_error_came_back():
    # One parallel batch over three SKUs, all failing, then the agent gives up: no retries.
    batch = _batch([("a", "get_price", {"sku": "1"}, True), ("b", "get_price", {"sku": "2"}, True),
                    ("c", "get_price", {"sku": "3"}, True)])
    assert retry_counts(batch) == {"retries": 0, "retried_tools": [], "same_args_repeats": 0, "repeated_tools": []}
    behaviour = target_behaviour(batch, "get_price", {"get_price": ["get_price_v2"]})
    assert behaviour["target_errored"] and behaviour["target_after_error"] == "stopped"
    # The same SKU twice in one batch is a repeat, not a retry; asking again after the error is a retry.
    calls = _batch([("a", "get_price", {"sku": "1"}, True), ("b", "get_price", {"sku": "1"}, True)],
                   [("c", "get_price", {"sku": "1"}, True), ("d", "get_price", {"sku": "2"}, False)],
                   [("e", "get_price_v2", {"sku": "1"}, False)])
    counts = retry_counts(calls)
    assert counts["retries"] == 1 and counts["same_args_repeats"] == 2 and counts["retried_tools"] == ["get_price"]
    behaviour = target_behaviour(calls, "get_price", {"get_price": ["get_price_v2"]})
    assert behaviour["target_retried"] and behaviour["target_fallback"] and behaviour["target_after_error"] == "both"
    clean = target_behaviour(_batch([("a", "get_price", {"sku": "1"}, False)]), "get_price", {})
    assert not clean["target_errored"] and clean["target_after_error"] is None


def test_proxy_draws_merge_proxies_in_first_use_order():
    entry = lambda label: {"label": label}
    logs = {"notes": [{"ts": 1, "draw_index": 0, "entry": entry("OP4/permanent")},
                      {"ts": 3, "draw_index": 0, "entry": entry("OP4/permanent")}],
            "inventory": [{"ts": 2, "draw_index": 0, "entry": entry("OP4/permanent")},
                          {"ts": 4, "draw_index": None, "entry": None}]}
    assert proxy_draws(logs) == ["OP4/permanent", "OP4/permanent"]


def _task():
    return {"id": "price_total", "servers": ["inventory"], "grade": {"type": "answer_number", "value": 56.55}}


def _score(tmp_path, events, timed_out=False, proxy=None, name="run-1"):
    run = tmp_path / name
    run.mkdir()
    (run / "claude.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    (run / "inventory-proxy.jsonl").write_text("".join(json.dumps(event) + "\n" for event in proxy or []))
    return score_run(_task(), "claude-haiku-5-5", "chaos", 1, "42:price_total:1", None, "medium", run,
                     {"inventory": str(run / "inventory.json")}, 12.3, timed_out)


def test_score_run_classifies_outcomes(tmp_path, monkeypatch):
    monkeypatch.setattr(arena, "ROOT", tmp_path)
    proxy = [{"ts": 1, "tool": "get_price", "fault": "error", "draw_index": 0, "fired": True,
              "entry": {"paper_type": "OP4_errorMessage", "persistence": "permanent", "label": "OP4/permanent"}}]
    row = _score(tmp_path, _stream([("mcp__inventory__get_price", True), ("mcp__inventory__get_price_v2", False)]),
                 proxy=proxy)
    assert row["outcome"] == "ok" and row["success"] and row["recovered"]
    assert row["first_entry"] == "OP4/permanent" and row["faults_by_op"] == {"error": 1}
    assert row["models_seen"] == ["claude-haiku-5-5"] and row["init_mcp_servers"][0]["status"] == "connected"
    for missing in ("seed", "target_tool", "drawn_entries", "model_usage", "num_turns", "artifact_dir"):
        assert missing in row


def test_score_run_harness_error_and_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(arena, "ROOT", tmp_path)
    no_result = _score(tmp_path, _stream([], result=False))
    assert no_result["outcome"] == "harness_error" and not no_result["success"]
    errored = _stream([], result=False) + [{"type": "result", "is_error": True, "result": "API Error: 500"}]
    assert _score(tmp_path, errored, name="run-2")["outcome"] == "harness_error"
    timed_out = _score(tmp_path, _stream([("mcp__inventory__get_price", False)]), timed_out=True, name="run-3")
    assert timed_out["outcome"] == "timeout" and not timed_out["success"]


def test_seeds_and_scoped_targets_are_paired():
    task = {"id": "budget_order", "fault_targets": ["get_note", "get_stock", "get_price", "place_order"]}
    assert run_seed(42, "budget_order", 3) == "42:budget_order:3"
    assert pick_target(42, task, 3) == pick_target(42, task, 3)
    assert len({pick_target(42, task, rep) for rep in range(1, 30)}) > 1


def test_claude_command_restricts_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_BIN", "/opt/claude")
    command = claude_command("do it", "claude-haiku-5-5", "medium", tmp_path / "mcp.json", ["notes", "inventory"])
    assert command[:3] == ["/opt/claude", "-p", "do it"]
    assert command[command.index("--tools") + 1] == ""
    allowed = command.index("--allowedTools")
    assert command[allowed + 1: allowed + 3] == ["mcp__notes", "mcp__inventory"]
    assert "--strict-mcp-config" in command and command[command.index("--output-format") + 1] == "stream-json"


def test_wilson_interval():
    assert wilson(0, 0) is None
    low, high = wilson(5, 10)
    assert abs(low - 0.2366) < 1e-3 and abs(high - 0.7634) < 1e-3
    assert wilson(10, 10)[1] == 1.0


def _row(model, condition, task, rep, success, **extra):
    return {"model": model, "condition": condition, "task": task, "rep": rep, "success": success, "effort": "medium",
            "outcome": "ok" if success else "fail", "retries": 1, "faults": extra.pop("faults", 0),
            "wall_time": 10, "tool_calls": 4, **extra}


def test_summary_rates_ratios_coverage_families_and_paired_view():
    rows = [
        _row("m", "clean", "t", 1, True), _row("m", "clean", "t", 2, True),
        _row("m", "chaos", "t", 1, True, faults=2, first_entry="OP4/permanent"),
        _row("m", "chaos", "t", 2, False, faults=0, first_entry="OP6/intermittent"),
        _row("m", "chaos_scoped", "t", 1, True, faults=1, first_entry="OP4/permanent"),
        _row("m", "clean", "u", 1, True, model_usage={"claude-x": {"inputTokens": 3, "costUSD": 0.5}},
             models_seen=["claude-x"]),
    ]
    summary = summarize(rows)
    model = summary["models"][0]
    assert model["conditions"]["clean"]["n"] == 3 and model["conditions"]["clean"]["success_rate"] == 1.0
    assert model["conditions"]["chaos"]["ci95"] == wilson(1, 2)
    assert model["resilience_ratio"] == 0.5 and model["scoped_resilience_ratio"] == 1.0
    assert model["models_seen"] == ["claude-x"] and model["effort"] == ["medium"]
    incomplete = {(c["task"], c["condition"]) for c in summary["coverage"] if c["incomplete"]}
    assert ("t", "chaos_scoped") in incomplete and ("t", "clean") not in incomplete
    chaos = summary["fault_families"]["chaos"]
    assert chaos["OP4/permanent"]["m"] == {"n": 1, "successes": 1}
    assert chaos["zero_dose"]["m"] == {"n": 1, "successes": 0}
    assert summary["paired"]["t#1"]["m"]["chaos"]["success"] is True
    assert summary["models_used"]["claude-x"] == {"runs": 1, "inputTokens": 3, "costUSD": 0.5}
    markdown = arena.summary_markdown(summary)
    assert "| m | chaos | 2 | 1 (50%) |" in markdown and "zero dose" in markdown


def test_stored_stream_keeps_only_scored_event_types(tmp_path):
    from bench.arena import _keep_stream_events
    stream = tmp_path / "claude.jsonl"
    events = _stream([("mcp__inventory__get_price", False)]) + [{"type": "vendor_status_event"}]
    stream.write_text("".join(json.dumps(event) + "\n" for event in events) + "not json\n")
    _keep_stream_events(stream)
    kept = [json.loads(line)["type"] for line in stream.read_text().splitlines()]
    assert kept == ["system", "assistant", "user", "result"]


def test_run_arena_results_file_keeps_default_results_and_summary(tmp_path, monkeypatch):
    from types import SimpleNamespace
    results = tmp_path / "results"
    results.mkdir()
    (tmp_path / "bench").mkdir()
    (tmp_path / "bench" / "tasks.yaml").write_text(json.dumps({"tasks": [{"id": "price_total"}]}))
    default_rows = '{"task": "price_total", "rep": 1}\n'
    (results / "runs.jsonl").write_text(default_rows)
    (results / "summary.json").write_text("{}")
    (results / "summary.md").write_text("# old")
    monkeypatch.setattr(arena, "ROOT", tmp_path)
    monkeypatch.setattr(arena, "RESULTS", results)
    monkeypatch.setattr(arena, "RUNS", results / "runs")
    # Rep 1 is already in the custom file (resume); rep 2 runs ok; rep 3 is a harness error.
    custom = results / "slice.jsonl"
    done = {"id": "r1", "task": "price_total", "model": "claude-opus-5-5", "condition": "chaos", "rep": 1,
            "effort": "medium"}
    custom.write_text(json.dumps(done) + "\n")
    calls = []

    def fake_run_one(task, model, condition, rep, seed, effort, run_cap, adapter=None):
        calls.append(rep)
        row = {**done, "adapter": adapter.name, "id": f"r{rep}", "rep": rep, "seed": f"{seed}:{task['id']}:{rep}", "target_tool": None,
               "outcome": "ok" if rep == 2 else "harness_error", "success": rep == 2, "tool_calls": 1, "faults": 0,
               "first_entry": None, "wall_time": 1.0, "artifact_dir": f"results/runs/r{rep}"}
        return row

    monkeypatch.setattr(arena, "run_one", fake_run_one)
    args = SimpleNamespace(task_file="bench/tasks.yaml", tasks=None, models="claude-opus-5-5", conditions="chaos",
                           reps=3, rep_range=None, rep_file=None, only_file=None, run_cap=600, parallel=1, seed="42",
                           effort="medium", results_file="results/slice.jsonl")
    assert arena.run_arena(args) == 0
    assert sorted(calls) == [2, 3]
    assert [json.loads(line)["rep"] for line in custom.read_text().splitlines()] == [1, 2]
    assert json.loads((results / "slice.harness_errors.jsonl").read_text())["rep"] == 3
    assert (results / "runs.jsonl").read_text() == default_rows
    assert (results / "summary.json").read_text() == "{}" and (results / "summary.md").read_text() == "# old"
    assert not (results / "harness_errors.jsonl").exists()
    assert arena.result_paths("results/runs.jsonl") == (results / "runs.jsonl", results / "harness_errors.jsonl", True)
