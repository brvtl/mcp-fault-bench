"""Chart the pre-registered fallback slice (original 10 + new 20 seeds) from the raw run records (needs matplotlib).

    python scripts/plot_fallback_slice.py [--runs results/runs.jsonl] [--ext-runs results/fallback_slice_ext.jsonl]
        [--reps bench/fallback_slice_reps.json] [--out media/fallback_slice.png] [--json results/fallback_slice_30.json]

Slice (docs/preregistration-shim.md, extended in docs/preregistration-fallback-slice-30.md): one-tool condition
(chaos_scoped), the no-shim run had at least one fault, its first drawn profile entry is OP4/permanent (the target
errors on every call) and the target tool has a fallback listed in profiles/shim.yaml. Each no-shim run is paired
with the chaos_scoped_shim run on the same (task, model, rep) seed. The script re-reads every run's fault-proxy log
to confirm that the first fired fault on the target is OP4/permanent in both arms.

Blocks: "original" = reps 1-10 of results/runs.jsonl (the published 10 seeds); "new" = the 20 pre-registered
(task, rep) seeds of bench/fallback_slice_reps.json, read from results/fallback_slice_ext.jsonl; "all" = both.
Per model and block it prints success counts, discordant pairs, the exact McNemar p and Bonferroni x3, writes them
to a JSON file and plots success out of n per model, without vs with the shim, each bar split by block.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import yaml  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.arena import mcnemar_exact  # noqa: E402
from mcp_fault_bench.winnable import load_rep_file  # noqa: E402

MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
NAMES = {"claude-opus-5-5": "Opus 5.5", "claude-sonnet-5-5": "Sonnet 5.5", "claude-haiku-5-5": "Haiku 5.5"}
BLOCKS = ("original", "new", "all")
BLOCK_NAMES = {"original": "original 10", "new": "new 20", "all": "all 30"}
FAMILY = len(MODELS)
SURFACE, INK, MUTED, GRID = "#0b1018", "#edf4fb", "#95a7b9", "#243142"
NO_SHIM, SHIM = "#b88a1a", "#2fa37f"
NO_SHIM_NEW, SHIM_NEW = "#6b5420", "#235f4f"  # the same hues blended toward the surface, for the new-20 segment


def first_target_fault(run: dict) -> str | None:
    """First fired fault on the target tool, read from the run's proxy logs (not from the summary fields)."""
    events = []
    for log in sorted((ROOT / run["artifact_dir"]).glob("*-proxy.jsonl")):
        for line in log.read_text().splitlines():
            event = json.loads(line)
            if event.get("tool") == run["target_tool"] and event.get("fired") and event.get("entry"):
                events.append((event["ts"], event["entry"]["label"]))
    return min(events)[1] if events else None


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _fallbacks() -> dict:
    return yaml.safe_load((ROOT / "profiles/shim.yaml").read_text())["fallbacks"]


def _in_slice(base: dict, fallbacks: dict) -> bool:
    return base["faults"] != 0 and base["target_tool"] in fallbacks and first_target_fault(base) == "OP4/permanent"


def _pair(index: dict, base: dict, model: str, task: str, rep: int) -> tuple[dict, dict]:
    shim = index[("chaos_scoped_shim", model, task, rep)]
    assert shim["seed"] == base["seed"] and shim["target_tool"] == base["target_tool"], (task, model, rep)
    assert first_target_fault(shim) == "OP4/permanent", ("shim arm drew a different fault", task, model, rep)
    return base, shim


def slice_pairs(runs_path: Path) -> dict[str, list[tuple[dict, dict]]]:
    """Original block: every chaos_scoped run with rep <= 10 that meets the slice criteria, paired with its shim run."""
    index = {(r["condition"], r["model"], r["task"], r["rep"]): r for r in load_rows(runs_path) if r["rep"] <= 10}
    fallbacks = _fallbacks()
    pairs: dict[str, list[tuple[dict, dict]]] = {m: [] for m in MODELS}
    for (condition, model, task, rep), base in sorted(index.items(), key=lambda kv: (kv[0][2], kv[0][3])):
        if condition != "chaos_scoped" or model not in pairs or not _in_slice(base, fallbacks):
            continue
        pairs[model].append(_pair(index, base, model, task, rep))
    return pairs


def ext_pairs(ext_path: Path, reps_path: Path) -> tuple[dict[str, list[tuple[dict, dict]]], list[dict]]:
    """New block: the pre-registered (task, rep) seeds, same criteria; seeds that fail them are returned as dropouts."""
    index = {(r["condition"], r["model"], r["task"], r["rep"]): r for r in load_rows(ext_path)}
    seeds = sorted((task, rep) for task, reps in load_rep_file(str(reps_path)).items() for rep in reps)
    fallbacks = _fallbacks()
    pairs: dict[str, list[tuple[dict, dict]]] = {m: [] for m in MODELS}
    dropped = []
    for model in MODELS:
        for task, rep in seeds:
            base = index[("chaos_scoped", model, task, rep)]
            if not _in_slice(base, fallbacks):
                dropped.append({"model": model, "task": task, "rep": rep, "faults": base["faults"],
                                "first_target_fault": first_target_fault(base), "run": base["id"]})
                continue
            pairs[model].append(_pair(index, base, model, task, rep))
    return pairs, dropped


def block_stats(pairs: list[tuple[dict, dict]]) -> dict:
    """Success counts, discordant pairs, exact McNemar p and Bonferroni x3 for one model's block of pairs."""
    b = sum(s["success"] and not n["success"] for n, s in pairs)
    c = sum(n["success"] and not s["success"] for n, s in pairs)
    p = mcnemar_exact(b, c)
    return {
        "n": len(pairs),
        "no_shim_success": sum(bool(n["success"]) for n, _ in pairs),
        "shim_success": sum(bool(s["success"]) for _, s in pairs),
        "b_shim_only": b,
        "c_no_shim_only": c,
        "mcnemar_p": p,
        "bonferroni_x3": min(1.0, FAMILY * p),
        "no_shim_stopped_after_first_error": sum(n["target_after_error"] == "stopped" for n, _ in pairs),
        "pairs": [{"task": n["task"], "rep": n["rep"], "no_shim_success": bool(n["success"]),
                   "shim_success": bool(s["success"]), "no_shim_run": n["id"], "shim_run": s["id"]}
                  for n, s in pairs],
    }


def build(runs_path: Path, ext_path: Path, reps_path: Path) -> dict:
    """Per model and block stats, seeds that left the new block, and timeouts among the new block's runs."""
    original = slice_pairs(runs_path)
    new, dropped = ext_pairs(ext_path, reps_path)
    seeds = {(task, rep) for task, reps in load_rep_file(str(reps_path)).items() for rep in reps}
    ext_rows = [r for r in load_rows(ext_path) if (r["task"], r["rep"]) in seeds]
    timeouts = {m: {arm: sum(r["outcome"] == "timeout" for r in ext_rows if r["model"] == m and r["condition"] == arm)
                    for arm in ("chaos_scoped", "chaos_scoped_shim")} for m in MODELS}
    models = {m: {"original": block_stats(original[m]), "new": block_stats(new[m]),
                  "all": block_stats(original[m] + new[m])} for m in MODELS}
    return {
        "preregistration": "docs/preregistration-fallback-slice-30.md",
        "sources": [str(runs_path.relative_to(ROOT)) if runs_path.is_relative_to(ROOT) else runs_path.name,
                    str(ext_path.relative_to(ROOT)) if ext_path.is_relative_to(ROOT) else ext_path.name],
        "test": "exact two-sided McNemar (binomial on discordant pairs), b = shim-only successes, "
                "c = no-shim-only successes; Bonferroni x3 across models = min(1, 3p)",
        "models": models,
        "left_slice_new_block": dropped,
        "timeouts_new_block": timeouts,
    }


def fmt_p(p: float) -> str:
    return f"{p:.1e}" if p < 0.001 else f"{p:.3g}"


def report(data: dict) -> None:
    for model in MODELS:
        for block in BLOCKS:
            s = data["models"][model][block]
            n = s["n"]
            print(f"{model} {BLOCK_NAMES[block]:>11}: n={n} no-shim {s['no_shim_success']}/{n} shim "
                  f"{s['shim_success']}/{n} b={s['b_shim_only']} c={s['c_no_shim_only']} "
                  f"McNemar p={fmt_p(s['mcnemar_p'])} Bonferroni x3={fmt_p(s['bonferroni_x3'])} "
                  f"(no-shim stopped after first error: {s['no_shim_stopped_after_first_error']})")
    dropped = data["left_slice_new_block"]
    print(f"seeds that left the slice (new block): {len(dropped)}")
    for d in dropped:
        print(f"  {d['model']} {d['task']} rep {d['rep']}: faults={d['faults']} "
              f"first target fault={d['first_target_fault']}")
    for model, arms in data["timeouts_new_block"].items():
        print(f"timeouts (new block) {model}: no-shim {arms['chaos_scoped']}, shim {arms['chaos_scoped_shim']}")


def plot(data: dict, out: Path) -> None:
    figure, axis = plt.subplots(figsize=(10, 5.625), dpi=160)
    figure.patch.set_facecolor(SURFACE)
    axis.set_facecolor(SURFACE)
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axis.spines[side].set_color(GRID)
    axis.tick_params(colors=MUTED, labelsize=10)
    axis.yaxis.grid(True, color=GRID, linewidth=0.6)
    axis.set_axisbelow(True)

    width = 0.36
    stats = data["models"]
    n_max = max(stats[m]["all"]["n"] for m in MODELS)
    for i, model in enumerate(MODELS):
        n = stats[model]["all"]["n"]
        for offset, key, colors, hatch in ((-width / 2, "no_shim_success", (NO_SHIM, NO_SHIM_NEW), None),
                                           (width / 2, "shim_success", (SHIM, SHIM_NEW), "////")):
            lower, upper = stats[model]["original"][key], stats[model]["new"][key]
            axis.bar(i + offset, lower, width, color=colors[0], hatch=hatch, edgecolor=SURFACE, linewidth=0.8)
            axis.bar(i + offset, upper, width, bottom=lower, color=colors[1], hatch=hatch, edgecolor=SURFACE,
                     linewidth=0.8)
            axis.text(i + offset, lower + upper + 0.5, f"{lower + upper}/{n}", ha="center", va="bottom", color=INK,
                      fontsize=12, fontweight="bold")
    labels = [f"{NAMES[m]}\nn = {stats[m]['all']['n']} paired runs\n"
              f"McNemar p = {fmt_p(stats[m]['all']['mcnemar_p'])}\nBonferroni ×3 = "
              f"{fmt_p(stats[m]['all']['bonferroni_x3'])}" for m in MODELS]
    axis.set_xticks(range(len(MODELS)), labels, color=INK, fontsize=10)
    axis.set_ylim(0, n_max + 9)
    axis.set_yticks(range(0, n_max + 1, 5))
    axis.set_ylabel("task success (runs)", color=MUTED, fontsize=10)
    n_original = max(stats[m]["original"]["n"] for m in MODELS)
    n_new = max(stats[m]["new"]["n"] for m in MODELS)
    handles = [plt.Rectangle((0, 0), 1, 1, color=NO_SHIM),
               plt.Rectangle((0, 0), 1, 1, facecolor=SHIM, hatch="////", edgecolor=SURFACE),
               plt.Rectangle((0, 0), 1, 1, color=MUTED),
               plt.Rectangle((0, 0), 1, 1, color="#4a5563")]
    legend = axis.legend(handles, ["no shim", "shim: error marked permanent, fallback named",
                                   f"lower segment: original {n_original} seeds",
                                   f"upper, darker segment: new {n_new} seeds"],
                         loc="upper left", frameon=False, fontsize=9.5, ncol=2)
    for text in legend.get_texts():
        text.set_color(INK)
    figure.suptitle("A tool fails on every call and a fallback tool exists", color=INK, fontsize=15,
                    fontweight="bold", x=0.06, ha="left", y=0.975)
    axis.set_title("Claude 5.5 via Claude Code, one-tool faults, first fault OP4/permanent on a target with a fallback",
                   color=MUTED, fontsize=9.5, loc="left", pad=10)
    figure.text(0.06, 0.035, "Pre-registered slice (docs/preregistration-shim.md, extended in "
                "docs/preregistration-fallback-slice-30.md); same (task, rep) seed in both arms;", color=MUTED,
                fontsize=8)
    figure.text(0.06, 0.012, "exact two-sided McNemar on all pairs. Source: results/runs.jsonl (reps 1-10) + "
                "results/fallback_slice_ext.jsonl + per-run proxy logs.", color=MUTED, fontsize=8)
    figure.tight_layout(rect=(0.02, 0.06, 1, 0.95))
    out.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out, facecolor=SURFACE)


def _shown(path: Path) -> Path:
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, default=ROOT / "results/runs.jsonl")
    parser.add_argument("--ext-runs", type=Path, default=ROOT / "results/fallback_slice_ext.jsonl")
    parser.add_argument("--reps", type=Path, default=ROOT / "bench/fallback_slice_reps.json")
    parser.add_argument("--out", type=Path, default=ROOT / "media/fallback_slice.png")
    parser.add_argument("--json", type=Path, default=ROOT / "results/fallback_slice_30.json")
    args = parser.parse_args()

    data = build(args.runs.resolve(), args.ext_runs.resolve(), args.reps.resolve())
    report(data)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=2) + "\n")
    print(f"wrote {_shown(args.json.resolve())}")
    plot(data, args.out)
    print(f"wrote {_shown(args.out.resolve())}")


if __name__ == "__main__":
    main()
