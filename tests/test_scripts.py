"""README results rendering keeps numbers tied to summary.json."""

import importlib.util
import json
from pathlib import Path

import pytest

from bench.arena import summarize

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("render_results", ROOT / "scripts" / "render_results.py")
render_results = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_results)


def test_render_results_replaces_only_the_marked_block():
    rows = [{"model": "m", "condition": "clean", "task": "t", "rep": 1, "success": True, "effort": "medium"},
            {"model": "m", "condition": "chaos", "task": "t", "rep": 1, "success": False, "effort": "medium",
             "faults": 1, "first_entry": "OP4/permanent"}]
    block = render_results.render(summarize(rows))
    assert "| m | chaos | 1 | 0 (0%) |" in block
    readme = (ROOT / "README.md").read_text()
    updated = render_results.update(readme, block)
    assert block in updated
    assert updated.split(render_results.START)[0] == readme.split(render_results.START)[0]
    assert updated.split(render_results.END)[1] == readme.split(render_results.END)[1]


def _script(name):
    module_spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def test_render_results_adds_winnable_shim_and_cap_sections():
    rows = [{"model": "m", "condition": condition, "task": "t", "rep": rep, "success": success, "effort": "medium",
             "outcome": "ok" if success else "fail", "first_entry": "OP2/permanent", "faults": 1}
            for condition, rep, success in (("clean", 1, True), ("chaos", 1, False), ("chaos_shim", 1, True),
                                            ("chaos", 11, False), ("chaos_shim", 11, True))]
    summary = summarize(rows)
    block = render_results.render(summary)
    assert block.index("| m | chaos | 1 | 0 (0%) |") < block.index("### Winnable subset")
    assert "docs/preregistration-shim.md" in block and "### Shim analysis" in block
    assert "### Extension: winnable reps (seed-selected, not paper-faithful)" in block
    assert "| chaos_shim - chaos | m | all incl. extension (seed-selected, not paper-faithful) | 2 |" in block
    assert block.index("| m | chaos | 1 | 0 (0%) |") < block.index("### Faulted-only success")
    assert "### Run caps" in block and "media/winnable.png" in block
    shim = render_results.render_shim(summary)
    assert "docs/preregistration-shim.md" in shim and "| chaos_shim vs chaos | m | faulted-only (no-shim) | 1 |" in shim
    assert "media/shim_lift.png" in shim and "#### Predictions vs results" in shim


def test_audit_public_flags_paths_secrets_and_emails(tmp_path):
    audit = _script("audit_public")
    box = "/" + "workspace/x"
    text = "\n".join(["fine line", f"cmd {box}", "key sk-" + "ant-api03-abcdefghijk", "task-risk-desk-ok",
                      "by someone@" + "example.com", "bot 123+me@users.noreply.github.com", "AK" + "IAABCDEFGHIJKLMNOP"])
    assert [(line, reason.split()[0]) for line, reason in audit.audit_text(text)] == [
        (2, "absolute"), (3, "Anthropic"), (5, "email"), (7, "AWS")]
    clean, dirty = tmp_path / "clean.txt", tmp_path / "dirty.txt"
    clean.write_text("nothing here\n")
    dirty.write_text("home /home" + "/box/.claude\n")
    assert audit.main([str(clean)]) == 0
    assert audit.main([str(clean), str(dirty)]) == 1


def test_audit_public_allows_owner_name_only_on_export_license_line(tmp_path):
    audit = _script("audit_public")
    name = "Pete" + "r Garb" + "ers"
    line = f"Copyright 2026 {name}"
    assert audit.audit_text(line, "LICENSE") == []
    assert [reason for _, reason in audit.audit_text(line, "README.md")] == ["personal name"]
    assert [reason for _, reason in audit.audit_text(line)] == ["personal name"]
    assert [reason for _, reason in audit.audit_text(f"{line}\nby {name}", "LICENSE")] == ["personal name"]
    assert [reason for _, reason in audit.audit_text("hi " + "Pete" + "y", "LICENSE")] == ["personal name"]
    assert [reason for _, reason in audit.audit_text("rate_limit" + "_event")] == ["rate-limit event record"]
    assert audit.audit_text("competitive peters-burg repeterd") == []
    export = tmp_path / "export"
    (export / ".git").mkdir(parents=True)
    (export / "LICENSE").write_text(f"{line}\n\nApache License\n")
    (export / ".git" / "config").write_text(f"name = {name}\n")
    assert audit.main(["--root", str(export)]) == 0
    (export / "NOTES.md").write_text(f"thanks {name}\n")
    assert audit.main(["--root", str(export)]) == 1


def test_scrub_paths_replaces_root_tmp_and_home(tmp_path):
    from bench.scrub import scrub_text
    root, home = "/srv/checkout/repo", "/home/someone"
    text = json.dumps({"command": f"{root}/.venv/bin/python", "cwd": "/tmp/chaos-agent-abc123",
                       "memory": f"{home}/.claude/projects/-tmp-chaos-agent-abc123/memory/",
                       "other": f"{root}-old/file", "plain": root})
    scrubbed = json.loads(scrub_text(text, root, home))
    assert scrubbed == {"command": "./.venv/bin/python", "cwd": "<tmp>",
                        "memory": "~/.claude/projects/-tmp-chaos-agent-abc123/memory/",
                        "other": f"{root}-old/file", "plain": "."}
    scrub = _script("scrub_paths")
    target = tmp_path / "mcp.json"
    target.write_text(text)
    assert scrub.main(["--root", root, "--home", home, "--dry-run", str(target)]) == 0 and target.read_text() == text
    scrub.main(["--root", root, "--home", home, str(target)])
    assert json.loads(target.read_text())["command"] == "./.venv/bin/python"


SUMMARY = json.loads((ROOT / "results" / "summary.json").read_text(encoding="utf-8"))


def test_preregistered_baselines_for_op4_permanent_by_target():
    """The pre-registration's main prediction rows: opus 8/10, sonnet 1/10, haiku 5/10; 3/19 each with no fallback."""
    rows = [json.loads(line) for line in (ROOT / "results" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    comparison = next(item for item in summarize(rows)["shim_analysis"]["comparisons"] if item["base"] == "chaos_scoped")
    found = {model: {label: (cell["baseline_successes"], cell["baseline_n"])
                     for label, cell in block["slices"]["op4_permanent_by_target"].items()}
             for model, block in comparison["models"].items()}
    eligible, none = "OP4/permanent first draw × fallback-eligible target", "OP4/permanent × no fallback"
    assert found == {"claude-opus-5-5": {eligible: (8, 10), none: (3, 19)},
                     "claude-sonnet-5-5": {eligible: (1, 10), none: (3, 19)},
                     "claude-haiku-5-5": {eligible: (5, 10), none: (3, 19)}}


def test_predictions_table_filled_from_summary():
    pending = render_results.predictions_markdown(SUMMARY)
    assert "| OP4/permanent, fallback-eligible target, n = 10 per model | Lift for all three." in pending
    assert "no-shim 1/10 → shim 10/10, b 9 c 0, p = 0.004" in pending and "no-shim 3/19 → shim 3/19" in pending
    rows = [{"model": "m", "condition": condition, "task": "t", "rep": 1, "success": success, "effort": "medium",
             "faults": 1, "first_entry": "OP4/permanent", "target_tool": "get_price", "wall_time": wall}
            for condition, success, wall in (("chaos_scoped", False, 60), ("chaos_scoped_shim", True, 20))]
    filled = render_results.predictions_markdown(summarize(rows))
    assert "no-shim 0/1 → shim 1/1, b 1 c 0, p = 1.000, median wall 60s → 20s" in filled


def test_lead_block_states_headline_numbers_from_summary():
    lead = render_results.render_lead(SUMMARY)
    assert "| claude-opus-5-5 | 60/60 (100%) | 15/60 (25%) | 40/60 (67%) |" in lead
    assert "| claude-sonnet-5-5 | 17/45 (38%) | 25%–52% | 13/58 (22%) | 14%–35% |" in lead
    assert "Discordant pairs 8 vs 0; exact two-sided McNemar p = 0.008; Bonferroni ×3 p = 0.023" in lead
    assert "seed-selected, not paper-faithful" in lead and "Resilience shim" in lead
    # Faulted-only numbers lead; the all-runs table follows, labeled as including unfaulted runs.
    assert lead.index("**Faulted-only**") < lead.index("**All runs, including runs where no fault fired**")
    assert lead.index("Counting only one-tool runs where at least one fault fired") < lead.index("Across all runs")


def test_readme_generated_blocks_match_summary():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert render_results.update_all(readme, SUMMARY) == readme, "run python scripts/render_results.py"
    assert readme.startswith("# MCP Fault Bench")
    assert "`chaosmonkey` still works as an alias" in readme


def test_faulted_only_chart_is_x_post_sized(tmp_path):
    pytest.importorskip("matplotlib")
    charts = _script("make_charts")
    charts.faulted_only(SUMMARY, tmp_path / "faulted_only.png")
    import matplotlib.image
    assert matplotlib.image.imread(tmp_path / "faulted_only.png").shape[:2] == (900, 1600)


def test_fallback_slice_seed_rule_reproduces_the_original_slice_and_extends_it():
    selector = _script("select_fallback_slice_seeds")
    import yaml
    from mcp_fault_bench.proxy import load_schedule
    from mcp_fault_bench.winnable import load_rep_file
    tasks = yaml.safe_load((ROOT / selector.TASKS).read_text())["tasks"]
    schedule = load_schedule(str(ROOT / selector.SCHEDULE))
    fallbacks = yaml.safe_load((ROOT / selector.SHIM).read_text())["fallbacks"]
    rows = [json.loads(line) for line in (ROOT / selector.RUNS).read_text().splitlines() if line.strip()]
    on_path = selector.on_path_tools(rows)
    original, _ = selector.select(tasks, schedule, fallbacks, on_path, 1, None, stop=10)
    assert selector.as_reps(original) == selector.ORIGINAL
    pairs, skipped = selector.select(tasks, schedule, fallbacks, on_path, 11, 20)
    assert len(pairs) == 20 and all(rep > 10 for _, rep, _ in pairs)
    assert len({(task, rep) for task, rep, _ in pairs}) == 20
    assert set(skipped) == {"price_total", "note_summary"}
    assert load_rep_file(str(ROOT / "bench" / "fallback_slice_reps.json")) == selector.as_reps(pairs)


def _fallback_slice_counts(stats):
    return {model: {block: (s["n"], s["no_shim_success"], s["shim_success"], s["b_shim_only"], s["c_no_shim_only"])
                    for block, s in blocks.items()} for model, blocks in stats["models"].items()}


def test_fallback_slice_blocks_from_raw_records():
    pytest.importorskip("matplotlib")
    plot = _script("plot_fallback_slice")
    data = plot.build(ROOT / "results" / "runs.jsonl", ROOT / "results" / "fallback_slice_ext.jsonl",
                      ROOT / "bench" / "fallback_slice_reps.json")
    assert _fallback_slice_counts(data) == {
        "claude-opus-5-5": {"original": (10, 8, 10, 2, 0), "new": (20, 19, 20, 1, 0), "all": (30, 27, 30, 3, 0)},
        "claude-sonnet-5-5": {"original": (10, 1, 10, 9, 0), "new": (20, 6, 20, 14, 0), "all": (30, 7, 30, 23, 0)},
        "claude-haiku-5-5": {"original": (10, 5, 10, 5, 0), "new": (20, 11, 20, 9, 0), "all": (30, 16, 30, 14, 0)},
    }
    assert data["left_slice_new_block"] == []
    assert all(arms == {"chaos_scoped": 0, "chaos_scoped_shim": 0} for arms in data["timeouts_new_block"].values())
    reps = json.loads((ROOT / "bench" / "fallback_slice_reps.json").read_text())
    seeds = {(task, rep) for task, values in reps.items() if isinstance(values, list) and task != "skipped"
             for rep in values}
    for model, blocks in data["models"].items():
        assert {(p["task"], p["rep"]) for p in blocks["new"]["pairs"]} == seeds
        assert all(p["rep"] <= 10 for p in blocks["original"]["pairs"])
        assert blocks["all"]["pairs"] == blocks["original"]["pairs"] + blocks["new"]["pairs"]
    sonnet = data["models"]["claude-sonnet-5-5"]
    assert sonnet["original"]["no_shim_stopped_after_first_error"] == 9
    assert sonnet["all"]["mcnemar_p"] == pytest.approx(2 / 2 ** 23)
    assert sonnet["all"]["bonferroni_x3"] == pytest.approx(3 * 2 / 2 ** 23)
    assert data["models"]["claude-opus-5-5"]["all"]["bonferroni_x3"] == pytest.approx(0.75)
    assert data == json.loads((ROOT / "results" / "fallback_slice_30.json").read_text())


def test_fallback_slice_block_stats_counts_discordant_pairs():
    pytest.importorskip("matplotlib")
    plot = _script("plot_fallback_slice")

    def run(i, success, stopped=False):
        return {"id": f"r{i}", "task": "t", "rep": i, "success": success,
                "target_after_error": "stopped" if stopped else "fallback"}

    pairs = [(run(1, False, True), run(1, True)), (run(2, True), run(2, False)), (run(3, True), run(3, True)),
             (run(4, False), run(4, True))]
    stats = plot.block_stats(pairs)
    assert (stats["n"], stats["no_shim_success"], stats["shim_success"]) == (4, 2, 3)
    assert (stats["b_shim_only"], stats["c_no_shim_only"], stats["no_shim_stopped_after_first_error"]) == (2, 1, 1)
    assert stats["mcnemar_p"] == 1.0 and stats["bonferroni_x3"] == 1.0
    assert stats["pairs"][0] == {"task": "t", "rep": 1, "no_shim_success": False, "shim_success": True,
                                 "no_shim_run": "r1", "shim_run": "r1"}
