"""Render the generated README blocks from results/summary.json.

    python scripts/render_results.py [--summary results/summary.json] [--readme README.md]

Three marker pairs are filled: LEAD (the summary and headline tables at the top), SHIM (the pre-registered shim
analysis and predictions vs results) and RESULTS (the full tables).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.arena import (HEADLINE_REPS, after_error_markdown, OP4_ELIGIBLE, OP4_NO_FALLBACK, SEED_SELECTED, _ci, _model_order,  # noqa: E402
                         _p, _pct, cap_markdown, extension_markdown, faulted_only_markdown, headline_mcnemar,
                         mcnemar_markdown, paired_markdown, shim_primary_markdown, shim_secondary_markdown,
                         summary_markdown, winnable_markdown)

START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"
LEAD_START, LEAD_END = "<!-- LEAD:START -->", "<!-- LEAD:END -->"
SHIM_START, SHIM_END = "<!-- SHIM:START -->", "<!-- SHIM:END -->"

PREREGISTRATION = "docs/preregistration-shim.md"
LABELS = {"clean": "clean", "chaos": "chaos (paper profile, all tools)", "chaos_scoped": "one-tool (chaos_scoped)"}


def _families(*prefixes: str, exclude: str | None = None):
    def select(block: dict) -> list[dict]:
        return [cell for family, cell in block["slices"].get("by_first_entry", {}).items()
                if family.startswith(prefixes) and family != exclude]
    return select


def _slice(*path: str):
    def select(block: dict) -> list[dict]:
        node = block["slices"]
        for key in path:
            node = node.get(key) or {}
        return [node] if node else []
    return select


def _primary(block: dict) -> list[dict]:
    return [block["primary"]]


# Slice and prediction text copied verbatim from the Predictions table of docs/preregistration-shim.md.
PREDICTIONS = (
    ("OP4/permanent, fallback-eligible target, n = 10 per model",
     "Lift for all three. Largest for sonnet (we expect ≥ 5/10) and haiku; little room for opus.",
     "chaos_scoped", _slice("op4_permanent_by_target", OP4_ELIGIBLE)),
    ("OP4/permanent, no fallback available (19 per model)",
     "No success change: the task's data is unreachable. Possibly fewer calls and shorter runs.",
     "chaos_scoped", _slice("op4_permanent_by_target", OP4_NO_FALLBACK)),
    ("OP4 intermittent or transient",
     "Possible harm: a recoverable error gets labelled PERMANENT. Too few runs to test.",
     "chaos_scoped", _families("OP4/", exclude="OP4/permanent")),
    ("OP6/permanent", "Same success, shorter wall time (35 s vs 60 s per hung call).",
     "chaos_scoped", _families("OP6/permanent")),
    ("OP1/OP2/OP3/OP5", "No effect: the shim does not touch successful responses.",
     "chaos_scoped", _families("OP1/", "OP2/", "OP3/", "OP5/")),
    ("All faulted one-tool runs (n = 45 per model)",
     "Positive lift for sonnet (primary hypothesis) and haiku; about zero for opus.", "chaos_scoped", _primary),
    ("Global chaos, OP4/permanent", "Stays at about 0: every tool is denied, so no fallback works.",
     "chaos", _families("OP4/permanent")),
    ("Clean", "No change.", "clean", _primary),
)


def _fraction(cell: dict) -> str:
    return f"{cell['successes']}/{cell['n']} ({_pct(cell['success_rate'])})" if cell and cell.get("n") else "-"


def _comparison(summary: dict, base: str) -> dict:
    for comparison in (summary.get("shim_analysis") or {}).get("comparisons") or []:
        if comparison["base"] == base:
            return comparison
    return {"models": {}}


def _prediction_result(cells: list[dict]) -> str:
    """No-shim → shim successes for one or more shim cells; pooled counts carry no test."""
    if not cells or not sum(cell["baseline_n"] for cell in cells):
        return "no runs in slice"
    baseline = f"{sum(cell['baseline_successes'] for cell in cells)}/{sum(cell['baseline_n'] for cell in cells)}"
    matched = [cell for cell in cells if cell["status"] == "ok"]
    if not matched:
        return f"no-shim {baseline} → shim pending"
    pairs = sum(cell["n_pairs"] for cell in matched)
    text = (f"no-shim {sum(cell['base_successes'] for cell in matched)}/{pairs} → "
            f"shim {sum(cell['shim_successes'] for cell in matched)}/{pairs}")
    if len(cells) > 1:
        return text + " (pooled, no test)"
    cell = cells[0]
    text += f", b {cell['b']} c {cell['c']}, p = {_p(cell['p'])}"
    return text + f", median wall {cell['median_wall_base']:.0f}s → {cell['median_wall_shim']:.0f}s"


def predictions_markdown(summary: dict) -> str:
    models = _model_order([model["model"] for model in summary["models"]])
    lines = ["| Slice (pre-registered) | Prediction (pre-registered, static text) | "
             + " | ".join(f"Result: {model}" for model in models) + " |", "|---|---|" + "---|" * len(models)]
    for label, prediction, base, select in PREDICTIONS:
        blocks = _comparison(summary, base)["models"]
        results = [_prediction_result(select(blocks[model])) if model in blocks else "no runs" for model in models]
        lines.append(f"| {label} | {prediction} | " + " | ".join(results) + " |")
    return "\n".join(lines) + "\n"


def render_shim(summary: dict) -> str:
    lines = [f"Generated by `scripts/render_results.py` from `results/summary.json`. Pre-registration: "
             f"[{PREREGISTRATION}]({PREREGISTRATION}). Config: [`profiles/shim.yaml`](profiles/shim.yaml) (classify mode)."]
    if not summary.get("shim_conditions"):
        lines += ["", "**Status: pending.** No shim runs yet; every shim column below reads \"pending\"."]
    primary = shim_primary_markdown(summary)
    lines += ["", primary.rstrip("\n")] if primary else ["", "No shim runs yet (pending)."]
    lines += ["", "#### Predictions vs results", "",
              "The slice and prediction columns are copied from the pre-registration. Result cells are generated: "
              "no-shim → shim successes on the paired (task, rep), faulted-only on the no-shim run except Clean; "
              "p = exact two-sided McNemar for single slices. Rows that pool several first entries show counts only.",
              "", predictions_markdown(summary).rstrip("\n")]
    if summary.get("after_error", {}).get("models"):
        lines += ["", "#### What the agent did after an error on the target", "",
                  "Generated from the Claude Code stream of each run, faulted pairs only. A retry is a call with the same "
                  "tool and the same arguments issued after that call's error result came back; calls in one parallel "
                  "batch are issued before any result returns, so they are not retries. \"Repeating a target call\" "
                  "counts any repeat of a (target, arguments) pair, including ones issued before an error came back. "
                  "After the target's first error a run either stopped (no retry, no fallback), called a fallback "
                  "named in [`profiles/shim.yaml`](profiles/shim.yaml), retried, or both; successes in brackets.",
                  "", after_error_markdown(summary).rstrip("\n")]
    secondary = shim_secondary_markdown(summary)
    if secondary:
        lines += ["", "<details><summary>Secondary slices (not confirmatory)</summary>", "", secondary.rstrip("\n"),
                  "", "</details>"]
    lines += ["", "![Shim vs no-shim on faulted one-tool runs](media/shim_lift.png)"]
    return "\n".join(lines)


def _range(cells: list[dict]) -> str:
    rates = sorted(cell["success_rate"] for cell in cells if cell and cell.get("n"))
    if not rates:
        return "n/a"
    return _pct(rates[0]) if _pct(rates[0]) == _pct(rates[-1]) else f"{_pct(rates[0])}–{_pct(rates[-1])}"


def render_lead(summary: dict) -> str:
    models = {model["model"]: model for model in summary["models"]}
    order = _model_order(list(models))
    efforts = sorted({effort for model in summary["models"] for effort in model["effort"]})
    headline = summary.get("headline") or {"n_runs": summary["n_runs"]}
    faulted = (summary.get("faulted_only") or {}).get("conditions") or {}
    cells = {condition: [models[name]["conditions"].get(condition) for name in order] for condition in LABELS}
    scoped_faulted = faulted.get("chaos_scoped") or {}
    test = headline_mcnemar(summary, "chaos_scoped", "all")
    test_faulted = headline_mcnemar(summary, "chaos_scoped", "faulted_only")
    short = {name: name.removeprefix("claude-").removesuffix("-5-5") for name in order}

    lines = [f"Generated by `scripts/render_results.py` from `results/summary.json`: reps 1–{HEADLINE_REPS}, the "
             f"paper-weighted sample ({headline['n_runs']} runs; {', '.join(f'`{name}`' for name in order)}; effort "
             f"{', '.join(efforts)}; agent Claude Code; {len(summary['tasks'])} small local tasks). Extension reps "
             f"({SEED_SELECTED}) never enter these numbers.", ""]
    summary_text = ""
    if scoped_faulted:
        summary_text = ("Counting only one-tool runs where at least one fault fired, Claude 5.5 task success is "
                        + ", ".join(f"{short[name]} {scoped_faulted[name]['successes']}/{scoped_faulted[name]['n']}"
                                    for name in order if name in scoped_faulted) + ". ")
    summary_text += (f"Across all runs (including runs where no fault fired), success falls from {_range(cells['clean'])} "
                     f"clean to {_range(cells['chaos'])} when every tool can fault under the paper's fault profile, and "
                     f"to {_range(cells['chaos_scoped'])} when faults hit one target tool.")
    if test:
        a, b = (test["model_a"], test["model_b"])
        summary_text += (f" On the same (task, rep) draws, {short[a]} beat {short[b]} {test['b']} times and lost "
                         f"{test['c']} times (exact McNemar p = {_p(test['p'])}).")
    lines += [summary_text]
    if faulted:
        lines += ["", f"**Faulted-only** (runs where at least one fault fired; Wilson 95% CI; reps 1–{HEADLINE_REPS})", "",
                  "| Model | One-tool faulted-only: success / n | 95% CI | Chaos (all tools) faulted-only: success / n | 95% CI |",
                  "|---|---:|---|---:|---|"]
        for name in order:
            one, every = scoped_faulted.get(name) or {}, (faulted.get("chaos") or {}).get(name) or {}
            lines.append(f"| {name} | {_fraction(one)} | {_ci(one) if one else '-'} | {_fraction(every)} | "
                         f"{_ci(every) if every else '-'} |")
    lines += ["", f"**All runs, including runs where no fault fired** (paper fault profile; success / n per cell, "
              f"reps 1–{HEADLINE_REPS})", "",
              "| Model | " + " | ".join(LABELS.values()) + " |", "|---|" + "---:|" * len(LABELS)]
    for name in order:
        lines.append(f"| {name} | " + " | ".join(_fraction(models[name]["conditions"].get(condition))
                                                for condition in LABELS) + " |")
    if test:
        same = (" The faulted-only scope (both runs faulted) gives the same discordant pairs."
                if test_faulted and (test_faulted["b"], test_faulted["c"]) == (test["b"], test["c"]) else "")
        lines += ["", f"**Headline between-model test:** {test['model_a']} vs {test['model_b']}, one-tool condition, "
                  f"{test['n_pairs']} pairs on (task, rep). Discordant pairs {test['b']} vs {test['c']}; exact two-sided "
                  f"McNemar p = {_p(test['p'])}; Bonferroni ×3 p = {_p(test['p_bonferroni_3'])} (family: the 3 model "
                  f"pairs within the one-tool condition); Bonferroni ×9 p = {_p(test['p_bonferroni_9'])} (family: 3 "
                  f"pairs × 3 conditions).{same} All pairs and conditions: "
                  f"[between-model McNemar](#between-model-mcnemar-reps-1{HEADLINE_REPS})."]
    status = "pending (no shim runs yet)" if not summary.get("shim_conditions") else "results below"
    lines += ["", f"**Pre-registered resilience shim:** {status}; see [Resilience shim](#resilience-shim)."]
    return "\n".join(lines)


def render(summary: dict) -> str:
    models = ", ".join(f"`{model['model']}`" for model in summary["models"])
    efforts = sorted({effort for model in summary["models"] for effort in model["effort"]})
    headline = summary.get("headline") or {"n_runs": summary["n_runs"]}
    extension = summary.get("extension") or {"n_runs": 0}
    lines = [f"Generated by `scripts/render_results.py` from `results/summary.json` ({summary['n_runs']} runs; "
             f"models {models}; effort {', '.join(efforts)}; up to {summary['reps']} repetitions per cell).", "",
             f"**Headline** (reps 1–{HEADLINE_REPS}, the paper-weighted sample; {headline['n_runs']} runs of clean, "
             f"chaos and chaos_scoped). Extension reps from `bench/winnable_reps.json` ({SEED_SELECTED}; "
             f"{extension['n_runs']} runs) never enter these rates.", "",
             summary_markdown(summary).rstrip("\n"), "",
             "<details><summary>Paired outcomes per (task, rep): c = clean, x = chaos, s = chaos_scoped</summary>", "",
             paired_markdown(summary).rstrip("\n"), "", "</details>", "",
             "![Success by condition, faulted-only](media/resilience.png)", "",
             "![Success by first drawn entry](media/fault_families.png)"]
    for title, block in ((f"Faulted-only success (reps 1–{HEADLINE_REPS})", faulted_only_markdown(summary)),
                         (f"Between-model McNemar (reps 1–{HEADLINE_REPS})", mcnemar_markdown(summary))):
        if block:
            lines += ["", f"### {title}", "", block.rstrip("\n")]
    winnable = winnable_markdown(summary)
    if winnable:
        lines += ["", "### Winnable subset", "",
                  "Runs whose first drawn entry is not OP4/permanent, within reps 1–10 (see "
                  f"[the winnable-rep rule](#winnable-draw-rep-extension-seed-selected-not-paper-faithful); the "
                  f"extension reps it picks are {SEED_SELECTED}).",
                  "", winnable.rstrip("\n"), "", f"![Winnable subset ({SEED_SELECTED})](media/winnable.png)"]
    lines += ["", "### Shim analysis", "",
              f"The pre-registered shim analysis ([{PREREGISTRATION}]({PREREGISTRATION})) is rendered in "
              "[Resilience shim](#resilience-shim)."]
    extension = extension_markdown(summary)
    if summary.get("extension_winnable") is not None or (summary.get("extension") or {}).get("n_runs"):
        lines += ["", f"### Extension: winnable reps ({SEED_SELECTED})", "", extension.rstrip("\n")]
    caps = cap_markdown(summary)
    if caps:
        lines += ["", "### Run caps", "", caps.rstrip("\n")]
    return "\n".join(lines)


def update(readme: str, block: str, start: str = START, end: str = END) -> str:
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if not pattern.search(readme):
        raise ValueError(f"README is missing the {start} / {end} markers")
    return pattern.sub(lambda _: f"{start}\n{block}\n{end}", readme)


def update_all(readme: str, summary: dict) -> str:
    for start, end, block in ((LEAD_START, LEAD_END, render_lead(summary)), (SHIM_START, SHIM_END, render_shim(summary)),
                              (START, END, render(summary))):
        readme = update(readme, block, start, end)
    return readme


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", default=str(ROOT / "results" / "summary.json"))
    parser.add_argument("--readme", default=str(ROOT / "README.md"))
    args = parser.parse_args()
    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    path = Path(args.readme)
    path.write_text(update_all(path.read_text(encoding="utf-8"), summary), encoding="utf-8")
    print(f"updated {path}")


if __name__ == "__main__":
    main()
