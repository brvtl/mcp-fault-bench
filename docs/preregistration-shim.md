# Pre-registration: permanent-error classification shim

Written and committed **before any shim evaluation run**, on 2026-10-27 at about 02:52 MT (see the commit timestamp). The baseline numbers below come from the existing no-shim rows in `results/runs.jsonl` (reps 1–10). No shim run on an evaluation seed had happened when this file was committed. Debugging and smoke tests use only `dev:<n>` seeds. The git history of this file is the record.

## Motivation

Iannillo et al. (arXiv:2610.32555) found that agents treat every tool failure as transient: they keep retrying a tool that will never recover. In our round-1 data, faults held permanently on one task-critical tool (the one-tool condition, `chaos_scoped`) are where Claude 5.5 models lose most runs. On faulted one-tool runs, OP4/permanent success was opus 11/29, sonnet 4/29 and haiku 8/29.

## Intervention (fixed before running)

The shim is opt-in (`--shim profiles/shim.yaml`). It sits between the agent and the fault injector. In `classify` mode it does **not retry** and does **not validate outputs**, which isolates the classification effect. It forwards every agent call unchanged, so the fault engine sees exactly the agent's calls. It only rewrites the error text the agent receives:

1. **Error result matching an auth, permission or not-found pattern.** Case-insensitive `access denied|forbidden|unauthori[sz]ed|permission denied|not found|\b401\b|\b403\b|\b404\b`. These patterns come from standard HTTP and API semantics, not from eval draws.
   - **Caveat:** this pattern matches the injector's OP4 text ("Access Denied to: <tool>"), which is identical for permanent, intermittent and transient OP4. The shim cannot see persistence; it is a heuristic a deployer could write.
   - **Action:** classified PERMANENT on the first occurrence.
2. **No response within `attempt_timeout_s` (35 s).** The shim answers with an error itself: UNRESPONSIVE, treat as PERMANENT. A late server response is discarded.
3. **Any other error result for the same tool twice in a row.** Classified PERMANENT on the second occurrence; the first is passed through unchanged.

Text sent for a PERMANENT classification: `PERMANENT: <tool> failed (<original error>). Do not retry <tool>; it will not recover in this session. Use fallback tool <X> instead.`

- **Fallbacks:** `<X>` comes from the `fallbacks` map in `profiles/shim.yaml`, which was written in round 2 from tool documentation before any shim run.
- **No fallback, or every fallback already classified PERMANENT:** `No working alternative tool is known; complete what you can and report what could not be done.`
- **`place_order`:** the message adds `The order may or may not have been placed; check list_orders before ordering again.`

## Conditions and runs

All runs use the same `42:<task>:<rep>` seeds as the no-shim rows, so pairs are matched on draws.

| Condition | Reps | Paired with |
|---|---|---|
| `chaos_scoped_shim` | 1–10 | `chaos_scoped` |
| `chaos_shim` | 1–10 | `chaos` |
| `clean_shim` | 1–10 | `clean` |

Models are claude-opus-5-5, claude-sonnet-5-5 and claude-haiku-5-5, all at effort medium, with the same 600 s cap.

## Primary analysis

- **Population:** one-tool condition, faulted-only. These are (task, model, rep) pairs where the **no-shim** run had at least one fault fired. Faulted status is defined on the baseline, not on the shim run, because the shim can change whether faults fire.
- **Test:** exact two-sided McNemar (binomial on discordant pairs), shim vs no-shim, per model. Bonferroni ×3 across models, α = 0.05.

**Secondary analyses** (reported, not confirmatory):

- by first drawn family
- fallback-eligible target (`get_price`, `get_price_v2`, `get_note`, `list_notes`) vs not
- both-faulted pairs
- all pairs
- global `chaos` faulted-only
- clean
- median wall time

## Predictions

| Slice (faulted-only, one-tool) | Baseline (no shim) | Prediction with shim |
|---|---|---|
| OP4/permanent, fallback-eligible target, n = 10 per model | opus 8/10, sonnet 1/10, haiku 5/10 | Lift for all three. Largest for sonnet (we expect ≥ 5/10) and haiku; little room for opus. |
| OP4/permanent, no fallback available (19 per model) | opus 3/19, sonnet 3/19, haiku 3/19 | No success change: the task's data is unreachable. Possibly fewer calls and shorter runs. |
| OP4 intermittent or transient | 1 run per model, all fail | Possible harm: a recoverable error gets labelled PERMANENT. Too few runs to test. |
| OP6/permanent | 4/4 for every model | Same success, shorter wall time (35 s vs 60 s per hung call). |
| OP1/OP2/OP3/OP5 | mostly succeed | No effect: the shim does not touch successful responses. |
| All faulted one-tool runs (n = 45 per model) | opus 25, sonnet 17, haiku 20 | Positive lift for sonnet (primary hypothesis) and haiku; about zero for opus. |
| Global chaos, OP4/permanent | 0/37 for every model | Stays at about 0: every tool is denied, so no fallback works. |
| Clean | 60/60 for every model | No change. |

## Power

Power is low. With 45 pairs, a model needs at least 7 discordant pairs all in one direction to pass Bonferroni ×3: p = 0.0156 × 3 = 0.047. A null or non-significant result will be reported as is. The shim is not tuned after seeing eval results; any later change would be a new, separately labelled condition.
