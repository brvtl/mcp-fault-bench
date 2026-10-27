# Pre-registration: fallback slice, 10 → 30 paired seeds

Written and committed **before any run on the new seeds**, on 2026-10-27 at about 09:50 MT (see the commit timestamp). No `chaos_scoped` or `chaos_scoped_shim` run with rep > 10 existed when this file was committed. The git history of this file is the record.

## Why

The fallback slice of the shim study ([preregistration-shim.md](preregistration-shim.md)) has 10 paired seeds per model: opus 8/10, sonnet 1/10 and haiku 5/10 without the shim, 10/10 each with it (recomputed from `results/runs.jsonl` by `scripts/plot_fallback_slice.py`). Ten seeds is small, and the shim results on those seeds were already known when this extension was planned. This run adds 20 new seeds from the same slice to firm up (or weaken) that result.

## The slice (unchanged)

One-tool condition (`chaos_scoped`, profile `profiles/paper_opp_scoped.yaml`), where:

1. the first drawn profile entry for the seed is **OP4/permanent** (the target tool errors on every call);
2. the target tool has a fallback in `profiles/shim.yaml`;
3. the no-shim run had at least one fault fired, and the first fired fault on the target is OP4/permanent in both arms (re-read from the per-run proxy logs, as in `scripts/plot_fallback_slice.py`).

## Seed selection (fixed before running)

Computed by `scripts/select_fallback_slice_seeds.py`, written to `bench/fallback_slice_reps.json`. It uses only seed strings, the profiles and the existing **clean** run records, never a chaos run outcome:

- Seed string `42:<task>:<rep>`, target from `bench.arena.pick_target`, first draw from `chaosmonkey.proxy.first_draw`. These are the same functions the arena uses.
- A (task, rep) is eligible if its first draw is OP4/permanent, its target has a fallback in `profiles/shim.yaml`, and the target is *on-path*: it appears in the proxy logs of every clean run (reps 1–10) of that task. This drops targets no agent calls in a clean run (price_total/get_price_v2 and note_summary/list_notes). Such runs would have zero faults, so they would leave the slice by criterion 3 anyway.
- Walk reps 11, 12, … (rep-major; within a rep, tasks in `bench/tasks.yaml` order). Keep the first 20 eligible pairs.
- Check: applied to reps 1–10, the same rule gives exactly the original 10 seeds (note_summary 1, 2, 9; budget_order 2, 10; cross_server_total 4, 5, 6; restock_cost 5, 9). `--check` asserts this.
- No overlap: every new seed has rep ≥ 11, and no `chaos_scoped*` record with rep > 10 exists. (The `chaos` extension rows use some of the same seed strings, but they belong to a different condition and the global profile, and they share no records with this run.)

**New 20 seeds:**

| Task | Reps | Target |
|---|---|---|
| cheapest_in_stock_order | 13, 16, 21, 23 | get_price |
| note_summary | 13, 14, 16, 23 | get_note |
| cross_server_total | 13, 14, 15, 20, 22 | get_note |
| cross_server_total | 16, 18 | get_price |
| price_total | 14, 17, 19, 23 | get_price |
| budget_order | 17 | get_price |

The task mix differs from the original 10. In particular, cheapest_in_stock_order and price_total are new to the slice. The slice definition is the same, but the task mix is not.

## Runs

- **Models:** claude-opus-5-5, claude-sonnet-5-5 and claude-haiku-5-5 via Claude Code, effort medium, with the same arena, prompts, tools and 600 s cap as the original slice.
- **Arms:** `chaos_scoped` (no shim) and `chaos_scoped_shim` (`profiles/shim.yaml`, classify mode, unchanged), on the same seed. The seed fixes the target and the draws, so pairs match across arms and models.
- **Total:** 20 seeds × 3 models × 2 arms = 120 runs.
- **Records:** raw records are appended to a new file, `results/fallback_slice_ext.jsonl`, with artifacts in `results/runs/`. The existing files (`results/runs.jsonl`, `results/summary.*` and the existing run directories) are not modified.
- **Command:** `python -m chaosmonkey arena --rep-file bench/fallback_slice_reps.json --conditions chaos_scoped,chaos_scoped_shim --results-file results/fallback_slice_ext.jsonl`
- **Harness errors:** a run where the agent CLI exits before producing a result is not an agent result. The arena re-queues it (unchanged behaviour), and every such rerun is reported.
- **Timeouts:** a run that hits the 600 s cap counts as a failure and is reported.
- **No replacement seeds, no early stopping, no shim or prompt changes.** If a seed leaves the slice for a model (criterion 3), that model's n drops below 20 (or 30), and this is reported.

## Analysis

- **Primary:** all 30 seeds combined (original 10 + new 20). Per model, exact two-sided McNemar (binomial on discordant pairs), shim vs no shim. Bonferroni ×3 across models, α = 0.05.
- **Also reported:** the same test on the new 20 alone, which is the only part not seen before planning. The original 10 are reported as already published.
- **For each model, arm and block** (original 10, new 20, all 30), we report:
  - success counts;
  - discordant pairs (shim-only successes, no-shim-only successes);
  - raw and Bonferroni p-values;
  - how many no-shim runs stopped after the first error.
- **Reporting:** the 30-seed result is reported whichever way it comes out, including a null or a reversal.

## Predictions

| Model | Original 10 (no shim → shim) | Prediction on new 20 |
|---|---|---|
| Opus 5.5 | 8/10 → 10/10 | High without the shim, little room for lift; not significant on its own. |
| Sonnet 5.5 | 1/10 → 10/10 | Large lift, significant after Bonferroni on the new 20 alone. |
| Haiku 5.5 | 5/10 → 10/10 | Lift, likely significant on all 30. |

## Power

To pass Bonferroni ×3 (raw p < 0.0167), a model needs at least 7 discordant pairs, all in one direction (p = 0.0156), or for example 10 vs 1 (p = 0.0117). Opus has little room: on the original 10 it had only 2 discordant pairs.
