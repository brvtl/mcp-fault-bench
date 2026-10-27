"""Render static charts from results/summary.json (needs the `media` extra: matplotlib).

    python scripts/make_charts.py [--summary results/summary.json] [--out media]

Writes media/faulted_only.png (1600x900, one-tool faulted-only success per model with Wilson 95% CIs, the
headline McNemar in the footer), media/resilience.png (clean vs faulted-only chaos and one-tool success per
model), media/fault_families.png (success by first drawn profile entry, per model), media/winnable.png (winnable
subset: chaos vs chaos_shim per model, Wilson 95% CI; seed-selected, not paper-faithful) and media/shim_lift.png
(pre-registered primary: shim vs no-shim on faulted one-tool runs per model, or "pending").
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.arena import DISPLAY_NAME, HEADLINE_REPS, SEED_SELECTED, _model_order, headline_mcnemar  # noqa: E402

# Dark surface + condition colors validated with the dataviz palette checker (also used by web/index.html).
SURFACE, INK, MUTED, GRID = "#0b1018", "#edf4fb", "#95a7b9", "#243142"
COLORS = {"clean": "#5f82ea", "chaos": "#e8506a", "chaos_scoped": "#b88a1a"}
MODEL_COLORS = ["#2fa37f", "#a070e0", "#c06a3a"]  # model identity, fixed order (validated, dark surface)
LABELS = {"clean": "clean (OP0)", "chaos": "chaos (paper OPP)", "chaos_scoped": "chaos_scoped (one tool)",
          "clean_shim": "clean + shim", "chaos_shim": "chaos + shim", "chaos_scoped_shim": "chaos_scoped + shim"}
# Shim variants keep their base condition's hue and add a hatch (identity is never color alone).
HATCH = "////"


def _base(condition: str) -> str:
    return condition.removesuffix("_shim")


def _style(axis) -> None:
    axis.set_facecolor(SURFACE)
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axis.spines[side].set_color(GRID)
    axis.tick_params(colors=MUTED, labelsize=9)
    axis.yaxis.grid(True, color=GRID, linewidth=0.6)
    axis.set_axisbelow(True)


def _figure(width: float, height: float):
    figure, axis = plt.subplots(figsize=(width, height), dpi=160)
    figure.patch.set_facecolor(SURFACE)
    _style(axis)
    return figure, axis


def _footer(figure, text: str = "", size: float = 8, stacked: bool = False) -> None:
    """Footer: optional note on the left and the display name on the right (or below the note when stacked)."""
    if text:
        figure.text(0.012, 0.075 if stacked else 0.02, text, ha="left", va="bottom", color=MUTED, fontsize=size)
    figure.text(0.012 if stacked else 0.988, 0.02, DISPLAY_NAME, ha="left" if stacked else "right", va="bottom",
                color=INK if stacked else MUTED, fontsize=size, fontweight="bold" if stacked else "normal")


def _save(figure, output: Path, bottom: float = 0.06) -> None:
    figure.tight_layout(rect=(0, bottom, 1, 1))
    figure.savefig(output, facecolor=SURFACE)
    plt.close(figure)


def _faulted(summary: dict, condition: str) -> dict:
    return ((summary.get("faulted_only") or {}).get("conditions") or {}).get(condition) or {}


def _bar(axis, x: float, cell: dict, width: float, fontsize: float, **style) -> None:
    """One success bar with a Wilson 95% CI whisker and "k/n" above the whisker."""
    rate = cell["success_rate"]
    axis.bar(x, rate, width, **style)
    low, high = cell["ci95"]
    axis.errorbar(x, rate, yerr=[[rate - low], [high - rate]], fmt="none", ecolor=INK, elinewidth=1.4, capsize=5)
    axis.text(x, high + 0.025, f"{cell['successes']}/{cell['n']}", ha="center", va="bottom", color=INK,
              fontsize=fontsize, fontweight="bold")


def _mcnemar_note(summary: dict) -> str:
    test = headline_mcnemar(summary, "chaos_scoped", "all")
    if not test:
        return ""
    short = lambda name: name.removeprefix("claude-").removesuffix("-5-5")  # noqa: E731
    return (f"McNemar {short(test['model_a'])} vs {short(test['model_b'])}, one tool: {test['b']} vs {test['c']} "
            f"discordant pairs, exact p = {test['p']:.3f}, Bonferroni ×3 p = {test['p_bonferroni_3']:.3f}")


def faulted_only(summary: dict, output: Path) -> None:
    """X-post sized (1600x900) headline chart: one-tool faulted-only success per model, global chaos lighter."""
    scoped, chaos = _faulted(summary, "chaos_scoped"), _faulted(summary, "chaos")
    models = _model_order(list(scoped) or [model["model"] for model in summary["models"]])
    # 160 dpi: 1 pt = 160/72 px, so 13 pt ≈ 29 px (labels stay at or above 28 px).
    figure, axis = plt.subplots(figsize=(10, 5.625), dpi=160)
    figure.patch.set_facecolor(SURFACE)
    _style(axis)
    axis.tick_params(labelsize=13)
    figure.text(0.012, 0.955, "Claude 5.5 under MCP faults: faulted-only success", color=INK, fontsize=21,
                fontweight="bold", va="top")
    figure.text(0.012, 0.885, "Runs where ≥1 fault fired · one target tool · paper fault profile · effort medium",
                color=MUTED, fontsize=13, va="top")
    if not scoped:
        _empty(axis, "no one-tool runs yet")
    groups = [("one target tool", scoped, 1.0, None)] + ([("all tools (global chaos)", chaos, 0.4, HATCH)] if chaos else [])
    width = 0.8 / len(groups)
    for offset, (label, cells, alpha, hatch) in enumerate(groups):
        for index, model in enumerate(models):
            cell = cells.get(model)
            if not cell or not cell["n"]:
                continue
            x = index + (offset - (len(groups) - 1) / 2) * width
            _bar(axis, x, cell, width * 0.9, 14 if offset == 0 else 13, color=MODEL_COLORS[index % len(MODEL_COLORS)],
                 alpha=alpha, hatch=hatch, edgecolor=SURFACE, linewidth=0)
    if scoped:
        axis.set_xticks(range(len(models)), models, color=INK, fontsize=14)
        axis.set_ylim(0, 1.0)
        axis.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        axis.set_ylabel("task success, Wilson 95% CI", color=MUTED, fontsize=13)
        handles = [matplotlib.patches.Patch(facecolor=MUTED, alpha=alpha, hatch=hatch, edgecolor=SURFACE, label=label)
                   for label, _, alpha, hatch in groups]
        axis.legend(handles=handles, frameon=False, labelcolor=INK, fontsize=13, loc="upper right", ncol=len(groups))
    _footer(figure, _mcnemar_note(summary), size=13, stacked=True)
    figure.tight_layout(rect=(0, 0.12, 1, 0.84))
    figure.savefig(output, facecolor=SURFACE)
    plt.close(figure)


def resilience(summary: dict, output: Path) -> None:
    """Clean (all runs) next to faulted-only chaos and one-tool success, per model, with n on every bar."""
    models = {model["model"]: model for model in summary["models"]}
    order = _model_order(list(models))
    groups = [("clean", "clean (all runs, no faults)", {name: models[name]["conditions"].get("clean") for name in order})]
    groups += [(condition, label, _faulted(summary, condition))
               for condition, label in (("chaos", "chaos, faulted-only (paper profile, all tools)"),
                                        ("chaos_scoped", "one tool, faulted-only (chaos_scoped)"))
               if _faulted(summary, condition)]
    figure, axis = _figure(10, 5)
    width = 0.8 / len(groups)
    for offset, (condition, label, cells) in enumerate(groups):
        for index, name in enumerate(order):
            cell = cells.get(name)
            if not cell or not cell["n"]:
                continue
            x = index + (offset - (len(groups) - 1) / 2) * width
            _bar(axis, x, cell, width * 0.92, 8.5, color=COLORS[condition], label=label if index == 0 else None)
    axis.set_xticks(range(len(order)), order, color=INK, fontsize=10)
    axis.set_ylim(0, 1.12)
    axis.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    axis.set_ylabel("task success (Wilson 95% CI)", color=MUTED)
    axis.set_title(f"Task success under faults: faulted-only runs (reps 1–{HEADLINE_REPS}; k/n on each bar)",
                   color=INK, loc="left", fontsize=12, pad=26)
    axis.legend(frameon=False, labelcolor=INK, fontsize=8.5, ncol=len(groups), loc="upper left",
                bbox_to_anchor=(0, 1.08))
    _footer(figure, "faulted-only = at least one fault fired in the run")
    _save(figure, output)


def fault_families(summary: dict, output: Path) -> None:
    """One row per chaos condition; bars per model for each first drawn entry."""
    families = summary.get("fault_families", {})
    models = _model_order([model["model"] for model in summary["models"]])  # same model colors as the other charts
    conditions = [condition for condition in ("chaos", "chaos_scoped") if families.get(condition)]
    widest = max((len(families[condition]) for condition in conditions), default=1)
    figure, axes = plt.subplots(max(len(conditions), 1), 1, dpi=160, squeeze=False,
                                figsize=(min(14, 2 + 0.9 * widest * max(len(models), 1) / 2), 2.9 * max(len(conditions), 1)))
    figure.patch.set_facecolor(SURFACE)
    width = 0.8 / max(len(models), 1)
    for axis, condition in zip(axes[:, 0], conditions or [None]):
        _style(axis)
        if condition is None:
            axis.text(0.5, 0.5, "no chaos runs yet", ha="center", color=MUTED, transform=axis.transAxes)
            continue
        groups = families[condition]
        keys = sorted(key for key in groups if key != "zero_dose") + (["zero_dose"] if "zero_dose" in groups else [])
        for model_index, model in enumerate(models):
            for column, key in enumerate(keys):
                cell = groups[key].get(model)
                if not cell:
                    continue
                x = column + (model_index - (len(models) - 1) / 2) * width
                rate = cell["successes"] / cell["n"]
                axis.bar(x, rate, width * 0.9, color=MODEL_COLORS[model_index % len(MODEL_COLORS)],
                         label=model if column == keys.index(next(k for k in keys if groups[k].get(model))) else None)
                axis.text(x, rate + 0.03, f"{cell['successes']}/{cell['n']}", ha="center", color=INK, fontsize=7)
        axis.set_xticks(range(len(keys)), ["no fault fired" if key == "zero_dose" else key.replace(" (", "\n(")
                                           for key in keys],
                        color=INK, fontsize=8.5)
        axis.set_ylim(0, 1.18)
        axis.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        axis.set_title(f"{LABELS[condition]}: success by first drawn entry", color=INK, loc="left", fontsize=11)
        axis.legend(frameon=False, labelcolor=INK, fontsize=8, loc="upper right", ncol=len(models),
                    bbox_to_anchor=(1, 1.2))
    _footer(figure, f"reps 1–{HEADLINE_REPS}, all runs")
    _save(figure, output, 0.05)


def _empty(axis, text: str) -> None:
    axis.text(0.5, 0.5, text, ha="center", va="center", color=MUTED, transform=axis.transAxes)
    axis.set_xticks([])
    axis.set_yticks([])


def winnable(summary: dict, output: Path) -> None:
    """Winnable subset (first draw not OP4/permanent), all reps: chaos vs chaos_shim per model."""
    conditions = (summary.get("winnable") or {}).get("conditions") or {}
    models = _model_order([model["model"] for model in summary["models"]])
    figure, axis = _figure(9, 4.2)
    shown = [condition for condition in ("chaos", "chaos_shim") if condition in conditions]
    if not shown:
        _empty(axis, "no chaos runs yet")
    width = 0.8 / max(len(shown), 1)
    for offset, condition in enumerate(shown):
        for index, model in enumerate(models):
            cell = conditions[condition].get(model, {}).get("all")
            if not cell or not cell["n"]:
                continue
            x = index + (offset - (len(shown) - 1) / 2) * width
            rate = cell["success_rate"]
            axis.bar(x, rate, width * 0.92, color=COLORS[_base(condition)], hatch=HATCH if condition.endswith("_shim") else None,
                     edgecolor=SURFACE, linewidth=0, label=LABELS[condition] if index == 0 else None)
            low, high = cell["ci95"]
            axis.errorbar(x, rate, yerr=[[rate - low], [high - rate]], fmt="none", ecolor=INK, elinewidth=1, capsize=3)
            axis.text(x, 0.02, f"{cell['successes']}/{cell['n']}", ha="center", va="bottom", color=INK, fontsize=7.5)
    if shown:
        axis.set_xticks(range(len(models)), models, color=INK)
        axis.set_ylim(0, 1.05)
        axis.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        axis.set_ylabel("task success (Wilson 95% CI)", color=MUTED)
        axis.legend(frameon=False, labelcolor=INK, fontsize=8.5, ncol=len(shown), loc="upper right", bbox_to_anchor=(1, 1.12))
    axis.set_title(f"Winnable subset, all reps incl. extension ({SEED_SELECTED})", color=INK, loc="left",
                   fontsize=12, pad=22)
    _footer(figure, "first draw not OP4/permanent; extension reps are picked by seed, so this view is not paper-faithful")
    _save(figure, output)


def shim_lift(summary: dict, output: Path) -> None:
    """Pre-registered primary: no-shim vs shim success per model on faulted one-tool pairs, or "pending"."""
    comparison = next((item for item in (summary.get("shim_analysis") or {}).get("comparisons") or []
                       if item["base"] == "chaos_scoped"), None)
    cells = {model: block["primary"] for model, block in (comparison or {}).get("models", {}).items()}
    order = _model_order(list(cells))
    figure, axis = _figure(10, 4.8)
    if not cells:
        _empty(axis, "no one-tool runs yet")
    width = 0.38
    for index, model in enumerate(order):
        cell = cells[model]
        base = {"successes": cell["baseline_successes"], "n": cell["baseline_n"]}
        if cell["status"] == "ok":
            base = {"successes": cell["base_successes"], "n": cell["n_pairs"]}
        shim = {"successes": cell["shim_successes"], "n": cell["n_pairs"]} if cell["status"] == "ok" else None
        for offset, (label, value) in enumerate((("no shim", base), ("shim", shim))):
            x = index + (offset - 0.5) * width
            if value is None:
                axis.text(x, 0.06, "pending", ha="center", va="bottom", color=MUTED, fontsize=10, rotation=90)
                continue
            rate = value["successes"] / value["n"] if value["n"] else 0
            axis.bar(x, rate, width * 0.92, color=COLORS["chaos_scoped"], hatch=HATCH if offset else None,
                     edgecolor=SURFACE, linewidth=0, label=label if index == 0 else None)
            axis.text(x, rate + 0.02, f"{value['successes']}/{value['n']}", ha="center", va="bottom", color=INK,
                      fontsize=10, fontweight="bold")
    if cells:
        notes = [f"McNemar p = {cells[m]['p']:.3f} (Bonf ×3 {cells[m]['p_bonferroni_3']:.3f})"
                 if cells[m]["status"] == "ok" else "shim arm pending" for m in order]
        axis.set_xticks(range(len(order)), [f"{m}\n{note}" for m, note in zip(order, notes)], color=INK, fontsize=9.5)
        axis.set_xlim(-0.6, len(order) - 0.4)
        axis.set_ylim(0, 1.1)
        axis.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        axis.set_ylabel("task success on paired (task, rep)", color=MUTED)
        handles = [matplotlib.patches.Patch(facecolor=COLORS["chaos_scoped"], label="no shim"),
                   matplotlib.patches.Patch(facecolor=COLORS["chaos_scoped"], hatch=HATCH, edgecolor=SURFACE,
                                            label="shim (classify)")]
        axis.legend(handles=handles, frameon=False, labelcolor=INK, fontsize=9, loc="upper right", ncol=2)
    status = "pending" if not summary.get("shim_conditions") else "pre-registered primary"
    axis.set_title(f"Shim vs no-shim on faulted one-tool runs ({status}; reps 1–{HEADLINE_REPS})", color=INK,
                   loc="left", fontsize=12)
    _footer(figure, "faulted = the no-shim run had at least one fault fired; see docs/preregistration-shim.md")
    _save(figure, output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", default=str(ROOT / "results" / "summary.json"))
    parser.add_argument("--out", default=str(ROOT / "media"))
    args = parser.parse_args()
    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    faulted_only(summary, out / "faulted_only.png")
    resilience(summary, out / "resilience.png")
    fault_families(summary, out / "fault_families.png")
    winnable(summary, out / "winnable.png")
    shim_lift(summary, out / "shim_lift.png")
    print(f"wrote faulted_only.png, resilience.png, fault_families.png, winnable.png and shim_lift.png in {out}")


if __name__ == "__main__":
    main()
