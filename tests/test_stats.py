"""Faulted-only, between-model McNemar and pre-registered shim analysis in the summary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.arena import (SEED_SELECTED, extension_markdown, mcnemar_exact, shim_markdown, summarize, wilson,
                         write_summary)

ROOT = Path(__file__).resolve().parents[1]
OPUS, SONNET, HAIKU = "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"


@pytest.fixture(scope="module")
def committed():
    rows = [json.loads(line) for line in (ROOT / "results" / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    return summarize(rows)


def test_faulted_only_on_committed_runs(committed):
    table = committed["faulted_only"]["conditions"]
    expected = {"chaos_scoped": {OPUS: (25, 45), SONNET: (17, 45), HAIKU: (20, 45)},
                "chaos": {OPUS: (13, 58), SONNET: (13, 58), HAIKU: (9, 58)}}
    for condition, per_model in expected.items():
        for model, (successes, n) in per_model.items():
            cell = table[condition][model]
            assert (cell["successes"], cell["n"]) == (successes, n), (condition, model)
            assert cell["ci95"] == wilson(successes, n)
            assert cell["no_fault_fired"] == 60 - n
    assert table["chaos_scoped"][OPUS]["no_fault_no_draw"] == 10 and table["chaos"][OPUS]["no_fault_no_draw"] == 0


def test_between_model_mcnemar_on_committed_runs(committed):
    tests = committed["between_model_mcnemar"]["conditions"]["chaos_scoped"]
    for scope in ("all", "faulted_only"):
        (item,) = [t for t in tests if t["scope"] == scope and (t["model_a"], t["model_b"]) == (OPUS, SONNET)]
        assert (item["b"], item["c"]) == (8, 0)
        assert item["p"] == pytest.approx(0.0078, abs=5e-5)
        assert item["p_bonferroni_3"] == pytest.approx(0.0234, abs=5e-5)
        assert item["p_bonferroni_9"] == pytest.approx(0.0703, abs=5e-5)
    assert set(committed["between_model_mcnemar"]["conditions"]) == {"clean", "chaos", "chaos_scoped"}


def test_mcnemar_exact_values():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(8, 0) == mcnemar_exact(0, 8) == 2 / 256
    assert mcnemar_exact(7, 0) == pytest.approx(0.015625)
    assert mcnemar_exact(3, 3) == 1.0


def test_committed_shim_arms_are_filled(committed):
    (primary, chaos, clean) = committed["shim_analysis"]["comparisons"]
    assert (primary["shim"], primary["base"], primary["confirmatory"]) == ("chaos_scoped_shim", "chaos_scoped", True)
    cell = primary["models"][SONNET]["primary"]
    assert cell["status"] == "ok" and (cell["baseline_successes"], cell["baseline_n"]) == (17, 45)
    assert (cell["shim_successes"], cell["b"], cell["c"]) == (26, 10, 1) and round(cell["p_bonferroni_3"], 3) == 0.035
    eligible = primary["models"][SONNET]["slices"]["fallback_eligible_target"]
    assert (eligible["eligible"]["baseline_n"], eligible["not eligible"]["baseline_n"]) == (20, 25)
    assert primary["models"][OPUS]["slices"]["by_first_entry"]["OP4/permanent"]["baseline_successes"] == 11
    assert "fallback_eligible_target" not in chaos["models"][OPUS]["slices"] and not clean["models"][OPUS]["slices"]
    text = shim_markdown(committed)
    assert "| chaos_scoped_shim vs chaos_scoped (primary) | claude-sonnet-5-5 | faulted-only (no-shim) | " \
           "45 | 17 | 26 | 10 | 1 | 0.012 | 0.035 |" in text


def _row(model, condition, task, rep, success, faults=1, **extra):
    return {"model": model, "condition": condition, "task": task, "rep": rep, "success": success, "faults": faults,
            "effort": "medium", "outcome": "ok" if success else "fail", "wall_time": extra.pop("wall_time", 10), **extra}


def test_shim_vs_no_shim_pairs_on_the_baseline_faulted_status():
    rows = []
    for rep in range(1, 9):  # baseline faulted and failing; the shim wins reps 1-7
        rows.append(_row("m", "chaos_scoped", "t", rep, False, first_entry="OP4/permanent", target_tool="get_price",
                         wall_time=100))
        rows.append(_row("m", "chaos_scoped_shim", "t", rep, rep <= 7, faults=0 if rep == 1 else 1, wall_time=40))
    rows.append(_row("m", "chaos_scoped", "t", 9, True, first_entry="OP2/permanent", target_tool="get_stock"))
    rows.append(_row("m", "chaos_scoped_shim", "t", 9, False))  # no-shim only
    rows.append(_row("m", "chaos_scoped", "t", 10, True, faults=0))  # unfaulted baseline: not in the primary
    rows.append(_row("m", "chaos_scoped_shim", "t", 10, False, faults=0))
    rows.append(_row("m", "chaos_scoped", "u", 1, False, first_entry="OP4/permanent", target_tool="get_note"))  # no shim
    rows.append(_row("m", "chaos_scoped_shim", "t", 11, True))  # extension rep: never in the analysis
    (comparison,) = summarize(rows)["shim_analysis"]["comparisons"]
    block = comparison["models"]["m"]
    primary = block["primary"]
    assert primary["status"] == "ok" and primary["baseline_n"] == 10 and primary["n_pairs"] == 9
    assert (primary["base_successes"], primary["shim_successes"], primary["b"], primary["c"]) == (1, 7, 7, 1)
    assert primary["p"] == round(mcnemar_exact(7, 1), 6) and primary["p_bonferroni_3"] == round(3 * mcnemar_exact(7, 1), 6)
    assert (primary["median_wall_base"], primary["median_wall_shim"]) == (100, 40)
    slices = block["slices"]
    assert slices["by_first_entry"]["OP4/permanent"]["b"] == 7 and slices["by_first_entry"]["OP2/permanent"]["c"] == 1
    assert slices["fallback_eligible_target"]["eligible"]["n_pairs"] == 8
    assert slices["fallback_eligible_target"]["not eligible"]["n_pairs"] == 1
    assert slices["both_faulted"]["n_pairs"] == 8 and slices["both_faulted"]["b"] == 6  # rep 1's shim run had no fault
    assert slices["all_pairs"]["n_pairs"] == 10 and slices["all_pairs"]["c"] == 2
    text = shim_markdown(summarize(rows))
    assert "| chaos_scoped_shim vs chaos_scoped (primary) | m | faulted-only (no-shim) | 9 of 10 | 1 | 7 | 7 | 1 |" in text


def test_extension_labels_say_seed_selected(tmp_path, monkeypatch):
    rows = [_row("m", "chaos", "t", 1, False, first_entry="OP2/permanent"),
            _row("m", "chaos", "t", 11, True, first_entry="OP2/permanent"),
            _row("m", "chaos_shim", "t", 1, True, first_entry="OP2/permanent"),
            _row("m", "chaos_shim", "t", 11, True, first_entry="OP2/permanent")]
    summary = summarize(rows)
    assert summary["extension_winnable"]["label"] == SEED_SELECTED
    assert summary["extension_winnable"]["conditions"]["chaos"]["m"]["n"] == 1
    text = extension_markdown(summary)
    lines = text.splitlines()
    headers = [line for line, following in zip(lines, lines[1:]) if following.startswith("|---")]
    assert len(headers) == 3  # winnable extension, shim lift, lift by first entry
    for line in headers + [line for line in lines if line.startswith("#")]:
        assert SEED_SELECTED in line, line
    assert "| chaos_shim - chaos | m | all incl. extension (seed-selected, not paper-faithful) | 2 |" in text
    from bench import arena
    monkeypatch.setattr(arena, "RESULTS", tmp_path)
    write_summary(rows)
    markdown = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert f"## Extension: winnable reps ({SEED_SELECTED})" in markdown
    assert markdown.index("| Model | Condition | n | Success |") < markdown.index("## Faulted-only success")
