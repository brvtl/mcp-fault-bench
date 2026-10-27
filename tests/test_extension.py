"""Winnable-draw rep extension, new arena conditions and caps, and the summary views built on them."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import yaml

from bench import arena
from bench.arena import (agent_events, build_mcp_config, plan_jobs, shim_stats, sign_test, summarize, wilson)
from mcp_fault_bench.proxy import ProfileDrawEngine, first_draw, load_schedule
from mcp_fault_bench.winnable import load_rep_file, winnable_reps, write_winnable_reps

ROOT = Path(__file__).resolve().parents[1]
PAPER = load_schedule(str(ROOT / "profiles" / "paper_opp.yaml"))
SCOPED = load_schedule(str(ROOT / "profiles" / "paper_opp_scoped.yaml"))


def test_first_draw_matches_the_engine_for_many_seeds():
    for index in range(3000):
        seed = f"dev:{index}"
        assert first_draw(PAPER, seed) == ProfileDrawEngine(PAPER, seed=seed).choose("any_tool")["entry"]["label"]
        # Scope and target do not change the first draw, so chaos_scoped sees the same entry.
        assert first_draw(SCOPED, seed) == ProfileDrawEngine(SCOPED, seed=seed, target="get_note").choose("get_note")["entry"]["label"]


def test_first_draw_is_null_without_entries():
    assert first_draw({"faults": []}, "dev:1") is None


def test_winnable_reps_rule_depends_only_on_seed_strings(tmp_path):
    kept, skipped = winnable_reps(PAPER, "dev", ["t1", "t2"], start=11, per_task=4, exclude=["OP4/permanent"])
    for task in ("t1", "t2"):
        assert len(kept[task]) == 4 and min(kept[task]) >= 11
        assert all(first_draw(PAPER, f"dev:{task}:{rep}") != "OP4/permanent" for rep in kept[task])
        assert all(label == "OP4/permanent" == first_draw(PAPER, f"dev:{task}:{rep}") for rep, label in skipped[task])
        walked = sorted(kept[task] + [rep for rep, _ in skipped[task]])
        assert walked == list(range(11, max(kept[task]) + 1))  # contiguous walk, nothing else considered
    output = tmp_path / "reps.json"
    document = write_winnable_reps(str(ROOT / "profiles" / "paper_opp.yaml"), "dev", 11, 4, ["OP4/permanent"],
                                   str(ROOT / "bench" / "tasks.yaml"), ["t1", "t2"], str(output))
    assert json.loads(output.read_text()) == document
    assert "never on a model" in document["rule"] and document["skipped"]["t1"] == skipped["t1"]
    assert load_rep_file(str(output)) == kept


def test_shipped_rep_file_follows_the_rule():
    document = json.loads((ROOT / "bench" / "winnable_reps.json").read_text())
    tasks = load_rep_file(str(ROOT / "bench" / "winnable_reps.json"))
    kept, skipped = winnable_reps(PAPER, "42", list(tasks), 11, 4, ["OP4/permanent"])
    assert tasks == kept and document["skipped"] == skipped


def _args(**values):
    return Namespace(**{"reps": 10, "rep_range": None, "rep_file": None, "only_file": None, "effort": "medium",
                        "run_cap": 600, **values})


def test_plan_jobs_rep_file_rep_range_only_file_and_resume(tmp_path):
    tasks = [{"id": "a"}, {"id": "b"}]
    rep_file = tmp_path / "reps.json"
    rep_file.write_text(json.dumps({"a": [11, 13], "b": [12], "rule": "r", "skipped": {}}))
    jobs = plan_jobs(tasks, ["m"], ["chaos", "chaos_shim"], [], _args(rep_file=str(rep_file)))
    assert [(task["id"], condition, rep) for task, _, condition, rep in jobs] == [
        ("a", "chaos", 11), ("a", "chaos_shim", 11), ("b", "chaos", 12), ("b", "chaos_shim", 12),
        ("a", "chaos", 13), ("a", "chaos_shim", 13)]
    done = [{"task": "a", "model": "m", "condition": "chaos", "rep": 11, "effort": "medium"}]
    assert len(plan_jobs(tasks, ["m"], ["chaos"], done, _args(rep_file=str(rep_file)))) == 2
    assert {rep for *_, rep in plan_jobs(tasks, ["m"], ["clean"], [], _args(rep_range="3-5"))} == {3, 4, 5}
    only = tmp_path / "only.json"
    only.write_text(json.dumps([{"task": "b", "model": "m", "rep": 2}, {"task": "a", "model": "x", "rep": 1}]))
    jobs = plan_jobs(tasks, ["m"], ["chaos_cap3000"], [], _args(only_file=str(only)))
    assert [(task["id"], model, condition, rep) for task, model, condition, rep in jobs] == [("b", "m", "chaos_cap3000", 2)]


def test_new_conditions_share_seeds_targets_and_schedules():
    assert arena.SCHEDULES["chaos_shim"] == arena.SCHEDULES["chaos"] == arena.SCHEDULES["chaos_cap3000"]
    assert arena.SCHEDULES["chaos_scoped_shim"] == arena.SCHEDULES["chaos_scoped"]
    assert arena.SCHEDULES["clean_shim"] == arena.SCHEDULES["clean"]
    assert set(arena.SCOPED) == {"chaos_scoped", "chaos_scoped_shim"}
    assert arena.RUN_CAPS == {"chaos_cap3000": 3000}
    task = {"id": "t", "servers": ["notes"]}
    plain = build_mcp_config(task, Path("s.yaml"), "dev:1", None, Path("run"), {"notes": "n.json"})
    shimmed = build_mcp_config(task, Path("s.yaml"), "dev:1", None, Path("run"), {"notes": "n.json"}, Path("shim.yaml"))
    assert "--shim" not in plain["mcpServers"]["notes"]["args"]
    args = shimmed["mcpServers"]["notes"]["args"]
    assert args[args.index("--shim") + 1] == "shim.yaml" and args.index("--shim") < args.index("--")


def test_scoped_shim_pairs_with_scoped_on_target_and_passes_the_classify_shim():
    tasks = yaml.safe_load((arena.ROOT / "bench" / "tasks.yaml").read_text(encoding="utf-8"))["tasks"]
    targets = []
    for task in tasks:
        for rep in range(1, 21):
            scoped = arena.run_target("chaos_scoped", 42, task, rep)
            assert arena.run_target("chaos_scoped_shim", 42, task, rep) == scoped
            assert scoped == arena.pick_target(42, task, rep) and scoped in (task.get("fault_targets") or [None])
            assert arena.run_target("chaos_shim", 42, task, rep) is arena.run_target("clean_shim", 42, task, rep) is None
            targets.append(scoped)
    assert len(set(targets)) > 2  # the draw varies across (task, rep)
    for condition in arena.SHIM_CONDITIONS:
        assert arena.run_shim(condition) == arena.ROOT / "profiles" / "shim.yaml"
        assert arena.shim_mode(condition) == "classify"
    for condition in arena.CONDITIONS + arena.CAP_CONDITIONS:
        assert arena.run_shim(condition) is None and arena.shim_mode(condition) is None


def test_shim_stats_and_agent_events_from_proxy_logs():
    events = [{"ts": 5.0, "latency": 4.0, "layer": "shim", "tool": "get_price",
               "shim": {"attempts": 4, "retried": 3, "validation_failures": 4, "timed_out": False, "final": "error",
                        "attempt_faults": ["random_value"] * 4}},
              {"ts": 1.5, "latency": 0.5, "layer": "shim", "tool": "get_stock",
               "shim": {"attempts": 1, "retried": 0, "validation_failures": 0, "timed_out": True, "final": "error",
                        "attempt_faults": [None]}},
              {"ts": 6.0, "latency": 0.1, "layer": "shim", "tool": "get_note",
               "shim": {"attempts": 2, "retried": 1, "validation_failures": 0, "timed_out": False, "final": "ok",
                        "attempt_faults": ["error", None]}}]
    assert shim_stats(events) == {"shim_calls": 3, "shim_retries": 4, "shim_validation_failures": 4,
                                  "shim_timeouts": 1, "shim_errors": 2}
    assert [(event["tool"], event["fault"]) for event in agent_events(events)] == [
        ("get_price", "shim_error"), ("get_stock", "shim_error"), ("get_note", None)]


def _stream(tools):
    events = [{"type": "system", "subtype": "init", "model": "m", "mcp_servers": [{"name": "inventory", "status": "connected"}]}]
    for index, (name, is_error) in enumerate(tools):
        events.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{index}", "name": name}]}})
        events.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{index}", "is_error": is_error}]}})
    events.append({"type": "result", "is_error": False, "result": "FINAL: 56.55"})
    return events


def test_score_run_records_cap_and_shim_counters(tmp_path, monkeypatch):
    monkeypatch.setattr(arena, "ROOT", tmp_path)
    run = tmp_path / "run"
    run.mkdir()
    (run / "claude.jsonl").write_text("".join(json.dumps(e) + "\n" for e in _stream(
        [("mcp__inventory__get_price", True), ("mcp__inventory__get_price_v2", False)])))
    proxy = [{"ts": 1, "tool": "get_price", "fault": "error", "draw_index": 0, "downstream_id": "s1",
              "entry": {"label": "OP4/permanent"}},
             {"ts": 2, "tool": "get_price", "fault": "error", "draw_index": 0, "downstream_id": "s2",
              "entry": {"label": "OP4/permanent"}},
             {"ts": 3, "latency": 2, "layer": "shim", "tool": "get_price",
              "shim": {"attempts": 2, "retried": 1, "validation_failures": 0, "timed_out": False, "final": "error",
                       "attempt_faults": ["error", "error"]}},
             {"ts": 4, "tool": "get_price_v2", "fault": "error", "draw_index": 0, "downstream_id": "s3",
              "entry": {"label": "OP4/permanent"}},
             {"ts": 5, "tool": "get_price_v2", "fault": None, "draw_index": 1, "downstream_id": "s4",
              "entry": {"label": "OP2/permanent"}},
             {"ts": 5, "latency": 1, "layer": "shim", "tool": "get_price_v2",
              "shim": {"attempts": 2, "retried": 1, "validation_failures": 0, "timed_out": False, "final": "ok",
                       "attempt_faults": ["error", None]}}]
    (run / "inventory-proxy.jsonl").write_text("".join(json.dumps(e) + "\n" for e in proxy))
    task = {"id": "price_total", "servers": ["inventory"], "grade": {"type": "answer_number", "value": 56.55}}
    row = arena.score_run(task, "m", "chaos_shim", 11, "dev:x", None, "medium", run, {}, 4.0, False, 3000)
    assert row["run_cap"] == 3000 and row["capped"] is False and row["shim"] is True
    assert row["shim_mode"] == "classify"
    assert row["faults"] == 3 and row["faults_by_op"] == {"error": 3}  # downstream attempts, not shim events
    assert row["shim_retries"] == 2 and row["shim_calls"] == 2 and row["shim_errors"] == 1
    # Agent-level view: get_price failed and the agent switched to v2, a fallback rather than a retry.
    assert row["retries"] == 0 and row["used_fallback_tool"]
    assert row["drawn_entries"] == ["OP4/permanent", "OP2/permanent"]


def test_sign_test_exact_values():
    assert sign_test(0, 0) == 1.0
    assert sign_test(5, 0) == 0.0625
    assert abs(sign_test(8, 2) - 0.109375) < 1e-9
    assert sign_test(3, 3) == 1.0


def _row(model, condition, task, rep, success, **extra):
    return {"model": model, "condition": condition, "task": task, "rep": rep, "success": success, "effort": "medium",
            "outcome": extra.pop("outcome", "ok" if success else "fail"), "wall_time": extra.pop("wall_time", 10),
            "faults": 1, **extra}


def test_summary_headline_excludes_extension_reps_and_reports_new_views():
    rows = [
        _row("m", "clean", "t", 1, True),
        _row("m", "chaos", "t", 1, False, first_entry="OP4/permanent"),
        _row("m", "chaos", "t", 2, False, first_entry="OP2/permanent", outcome="timeout", wall_time=600),
        _row("m", "chaos", "t", 3, True, first_entry=None),
        _row("m", "chaos", "t", 11, False, first_entry="OP6/permanent"),  # extension rep
        _row("m", "chaos_shim", "t", 1, False, first_entry="OP4/permanent"),
        _row("m", "chaos_shim", "t", 2, True, first_entry="OP2/permanent", run_cap=600),
        _row("m", "chaos_shim", "t", 3, True, first_entry=None),
        _row("m", "chaos_shim", "t", 11, True, first_entry="OP6/permanent"),
        _row("m", "chaos_cap3000", "t", 2, True, first_entry="OP2/permanent", run_cap=3000, wall_time=900),
    ]
    summary = summarize(rows)
    chaos = summary["models"][0]["conditions"]["chaos"]
    assert chaos["n"] == 3 and chaos["successes"] == 1  # rep 11 is not in the headline
    assert summary["conditions"] == ["clean", "chaos"] and summary["reps"] == 3
    assert summary["headline"]["reps"] == [1, 10] and summary["extension"]["n_runs"] == 2
    assert summary["extension"]["reps"] == {"t": [11]}
    assert "t#11" not in summary["paired"]
    assert all(key.endswith(("#1", "#2", "#3")) for key in summary["paired"])
    assert summary["models"][0]["shim_conditions"]["chaos_shim"]["n"] == 3

    winnable = summary["winnable"]["conditions"]
    assert winnable["chaos"]["m"]["headline"] == {"n": 2, "successes": 1, "success_rate": 0.5, "ci95": wilson(1, 2)}
    assert winnable["chaos"]["m"]["all"]["n"] == 3  # null first_entry kept, OP4/permanent dropped
    assert winnable["chaos_shim"]["m"]["all"] == {"n": 3, "successes": 3, "success_rate": 1.0, "ci95": wilson(3, 3)}

    lift = summary["shim_lift"]["chaos_shim - chaos"]["m"]
    assert lift["all"] == {"n_pairs": 4, "base_successes": 1, "shim_successes": 3, "base_rate": 0.25,
                           "shim_rate": 0.75, "lift": 0.5, "improved": 2, "worsened": 0, "sign_test_p": 0.5}
    assert lift["headline"]["n_pairs"] == 3 and lift["headline"]["improved"] == 1
    families = summary["shim_lift_by_family"]["chaos_shim - chaos"]
    assert families["OP2/permanent"]["m"]["improved"] == 1 and families["no draw"]["m"]["n_pairs"] == 1

    caps = {(item["condition"]): item for item in summary["cap_stats"]}
    assert caps["chaos"] == {"model": "m", "condition": "chaos", "n": 4, "capped": 1, "run_cap": [600.0]}
    assert caps["chaos_cap3000"]["run_cap"] == [3000.0]
    sensitivity = summary["cap_sensitivity"]
    assert sensitivity["rows"] == [{"task": "t", "model": "m", "rep": 2, "chaos_outcome": "timeout",
                                    "chaos_wall_time": 600, "cap_outcome": "ok", "cap_wall_time": 900,
                                    "cap_run_cap": 3000}]
    assert sensitivity["by_model"]["m"]["flipped_to_success"] == 1 and sensitivity["by_model"]["m"]["cap_capped"] == 0

    assert "| m | chaos | 3 | 1 (33%) |" in arena.summary_markdown(summary)
    assert ("| chaos_shim - chaos | m | all incl. extension (seed-selected, not paper-faithful) | 4 | 1 | 3 | +50% | 2 | "
            "0 | 0.500 |") in arena.extension_markdown(summary)
    assert "| m | chaos | 1/2 (50%, 9%–91%) |\n" in arena.winnable_markdown(summary)
    assert "| m | chaos | 0/1 (0%, 0%–79%) | 1/3 (33%, 6%–79%) |" in arena.extension_markdown(summary)
    assert "| chaos_shim vs chaos | m | faulted-only (no-shim) | 3 | 1 | 2 | 1 | 0 |" in arena.shim_markdown(summary)
    assert "| t | m | 2 | timeout | 600s | ok | 900s |" in arena.cap_markdown(summary)


def test_summary_of_recorded_runs_keeps_headline_tables():
    rows = arena._read_jsonl(ROOT / "results" / "runs.jsonl")
    if not rows:
        return
    recorded = json.loads((ROOT / "results" / "summary.json").read_text())
    summary = json.loads(json.dumps(summarize(rows)))
    for key in ("n_runs", "reps", "conditions", "tasks", "coverage", "fault_families", "paired", "models_used"):
        assert summary[key] == recorded[key], key
    for new, old in zip(summary["models"], recorded["models"]):
        assert new["conditions"] == old["conditions"]
