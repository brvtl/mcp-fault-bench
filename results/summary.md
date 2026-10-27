# Arena summary

1168 runs from `results/runs.jsonl`.

## Headline (reps 1–10, paper-weighted; 540 runs)

`headline` = reps 1–10. `extension` = rep-file reps (79 runs), which never enter the headline rates.

| Model | Condition | n | Success | 95% CI | Tool calls | Retries | Faults fired | Wall time | Timeouts | Built-in tool runs |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| claude-haiku-5-5 | clean | 60 | 60 (100%) | 94%–100% | 8.7 | 0.00 | 0.00 | 8s | 0 | 0 |
| claude-haiku-5-5 | chaos | 60 | 11 (18%) | 11%–30% | 7.7 | 0.52 | 7.18 | 51s | 2 | 0 |
| claude-haiku-5-5 | chaos_scoped | 60 | 35 (58%) | 46%–70% | 9.1 | 0.30 | 2.00 | 34s | 0 | 0 |
| claude-opus-5-5 | clean | 60 | 60 (100%) | 94%–100% | 8.2 | 0.00 | 0.00 | 12s | 0 | 0 |
| claude-opus-5-5 | chaos | 60 | 15 (25%) | 16%–37% | 9.0 | 0.23 | 8.53 | 60s | 3 | 0 |
| claude-opus-5-5 | chaos_scoped | 60 | 40 (67%) | 54%–77% | 9.3 | 0.12 | 1.95 | 33s | 0 | 0 |
| claude-sonnet-5-5 | clean | 60 | 60 (100%) | 94%–100% | 8.2 | 0.00 | 0.00 | 13s | 0 | 0 |
| claude-sonnet-5-5 | chaos | 60 | 15 (25%) | 16%–37% | 6.2 | 0.13 | 5.75 | 52s | 1 | 0 |
| claude-sonnet-5-5 | chaos_scoped | 60 | 32 (53%) | 41%–65% | 7.6 | 0.03 | 1.75 | 31s | 0 | 0 |

| Model | Effort | Resilience (chaos ÷ clean) | Scoped resilience (chaos_scoped ÷ clean) | Models seen |
|---|---|---:|---:|---|
| claude-haiku-5-5 | medium | 0.18 | 0.58 | claude-haiku-5-5 |
| claude-opus-5-5 | medium | 0.25 | 0.67 | claude-opus-5-5 |
| claude-sonnet-5-5 | medium | 0.25 | 0.53 | claude-sonnet-5-5 |

### Coverage (successes / runs per task)

| Model | Task | clean | chaos | chaos_scoped |
|---|---|---:|---:|---:|
| claude-haiku-5-5 | budget_order | 10/10 | 3/10 | 5/10 |
| claude-haiku-5-5 | cheapest_in_stock_order | 10/10 | 1/10 | 7/10 |
| claude-haiku-5-5 | cross_server_total | 10/10 | 1/10 | 2/10 |
| claude-haiku-5-5 | note_summary | 10/10 | 2/10 | 5/10 |
| claude-haiku-5-5 | price_total | 10/10 | 2/10 | 10/10 |
| claude-haiku-5-5 | restock_cost | 10/10 | 2/10 | 6/10 |
| claude-opus-5-5 | budget_order | 10/10 | 3/10 | 5/10 |
| claude-opus-5-5 | cheapest_in_stock_order | 10/10 | 2/10 | 7/10 |
| claude-opus-5-5 | cross_server_total | 10/10 | 2/10 | 6/10 |
| claude-opus-5-5 | note_summary | 10/10 | 2/10 | 6/10 |
| claude-opus-5-5 | price_total | 10/10 | 3/10 | 10/10 |
| claude-opus-5-5 | restock_cost | 10/10 | 3/10 | 6/10 |
| claude-sonnet-5-5 | budget_order | 10/10 | 3/10 | 4/10 |
| claude-sonnet-5-5 | cheapest_in_stock_order | 10/10 | 2/10 | 7/10 |
| claude-sonnet-5-5 | cross_server_total | 10/10 | 2/10 | 3/10 |
| claude-sonnet-5-5 | note_summary | 10/10 | 2/10 | 4/10 |
| claude-sonnet-5-5 | price_total | 10/10 | 3/10 | 10/10 |
| claude-sonnet-5-5 | restock_cost | 10/10 | 3/10 | 4/10 |

### chaos: success by first drawn entry

| First entry | claude-haiku-5-5 | claude-opus-5-5 | claude-sonnet-5-5 |
|---|---:|---:|---:|
| OP2/intermittent | 0/1 | 0/1 | 0/1 |
| OP2/permanent | 6/10 | 10/10 | 10/10 |
| OP3/permanent | 1/1 | 1/1 | 1/1 |
| OP4/intermittent | 3/4 | 3/4 | 3/4 |
| OP4/permanent | 0/37 | 0/37 | 0/37 |
| OP4/transient | 0/1 | 0/1 | 0/1 |
| OP5/intermittent | 0/1 | 0/1 | 0/1 |
| OP5/permanent | 1/1 | 1/1 | 1/1 |
| OP6/permanent | 0/4 | 0/4 | 0/4 |
| zero dose (no fault fired) | 2/2 | 2/2 | 2/2 |

### chaos_scoped: success by first drawn entry

| First entry | claude-haiku-5-5 | claude-opus-5-5 | claude-sonnet-5-5 |
|---|---:|---:|---:|
| OP2/intermittent | 0/1 | 0/1 | 0/1 |
| OP2/permanent | 6/8 | 8/8 | 7/8 |
| OP3/permanent | 1/1 | 1/1 | 1/1 |
| OP4/intermittent | 4/4 | 4/4 | 4/4 |
| OP4/permanent | 8/29 | 11/29 | 4/29 |
| OP4/transient | 0/1 | 0/1 | 0/1 |
| OP5/intermittent | 1/1 | 1/1 | 1/1 |
| OP5/permanent | 1/1 | 1/1 | 1/1 |
| OP6/permanent | 4/4 | 4/4 | 4/4 |
| no draw (target not called) | 10/10 | 10/10 | 10/10 |
| zero dose (no fault fired) | 15/15 | 15/15 | 15/15 |

### Models used (from Claude Code modelUsage)

| Model id | Runs | Input tokens | Output tokens | Cache read | Cache write | Notional API cost (USD, not billed) |
|---|---:|---:|---:|---:|---:|---:|
| claude-haiku-5-5 | 385 | 3,276 | 441,618 | 7,679,810 | 1,739,860 | 0.65 |
| claude-opus-5-5 | 384 | 3,576 | 344,559 | 7,201,022 | 1,326,440 | 18.96 |
| claude-sonnet-5-5 | 386 | 3,074 | 296,133 | 5,880,921 | 1,274,136 | 8.65 |

## Paired outcomes (c = clean, x = chaos, s = chaos_scoped)

| Task # rep | claude-haiku-5-5 | claude-opus-5-5 | claude-sonnet-5-5 |
|---|---|---|---|
| budget_order#1 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| budget_order#2 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| budget_order#3 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| budget_order#4 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| budget_order#5 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| budget_order#6 | c✓ x✓ s✓ | c✓ x✓ s✓ | c✓ x✓ s✓ |
| budget_order#7 | c✓ x✓ s✓ | c✓ x✓ s✓ | c✓ x✓ s✓ |
| budget_order#8 | c✓ x✓ s✓ | c✓ x✓ s✓ | c✓ x✓ s✓ |
| budget_order#9 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| budget_order#10 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✗ |
| cheapest_in_stock_order#1 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| cheapest_in_stock_order#2 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| cheapest_in_stock_order#3 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| cheapest_in_stock_order#4 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| cheapest_in_stock_order#5 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| cheapest_in_stock_order#6 | c✓ x✗ s✓ | c✓ x✓ s✓ | c✓ x✓ s✓ |
| cheapest_in_stock_order#7 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| cheapest_in_stock_order#8 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| cheapest_in_stock_order#9 | c✓ x✓ s✓ | c✓ x✓ s✓ | c✓ x✓ s✓ |
| cheapest_in_stock_order#10 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| cross_server_total#1 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| cross_server_total#2 | c✓ x✓ s✓ | c✓ x✓ s✓ | c✓ x✓ s✓ |
| cross_server_total#3 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| cross_server_total#4 | c✓ x✗ s✗ | c✓ x✗ s✓ | c✓ x✗ s✗ |
| cross_server_total#5 | c✓ x✗ s✗ | c✓ x✗ s✓ | c✓ x✗ s✗ |
| cross_server_total#6 | c✓ x✗ s✗ | c✓ x✗ s✓ | c✓ x✗ s✗ |
| cross_server_total#7 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| cross_server_total#8 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| cross_server_total#9 | c✓ x✗ s✗ | c✓ x✓ s✓ | c✓ x✓ s✓ |
| cross_server_total#10 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| note_summary#1 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| note_summary#2 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✗ |
| note_summary#3 | c✓ x✓ s✓ | c✓ x✓ s✓ | c✓ x✓ s✓ |
| note_summary#4 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| note_summary#5 | c✓ x✓ s✗ | c✓ x✓ s✓ | c✓ x✓ s✗ |
| note_summary#6 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| note_summary#7 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| note_summary#8 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| note_summary#9 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| note_summary#10 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| price_total#1 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| price_total#2 | c✓ x✓ s✓ | c✓ x✓ s✓ | c✓ x✓ s✓ |
| price_total#3 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| price_total#4 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| price_total#5 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| price_total#6 | c✓ x✓ s✓ | c✓ x✓ s✓ | c✓ x✓ s✓ |
| price_total#7 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| price_total#8 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| price_total#9 | c✓ x✗ s✓ | c✓ x✓ s✓ | c✓ x✓ s✓ |
| price_total#10 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| restock_cost#1 | c✓ x✗ s✓ | c✓ x✓ s✓ | c✓ x✓ s✓ |
| restock_cost#2 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| restock_cost#3 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| restock_cost#4 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| restock_cost#5 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✗ |
| restock_cost#6 | c✓ x✓ s✓ | c✓ x✓ s✓ | c✓ x✓ s✓ |
| restock_cost#7 | c✓ x✗ s✗ | c✓ x✗ s✗ | c✓ x✗ s✗ |
| restock_cost#8 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✓ |
| restock_cost#9 | c✓ x✗ s✓ | c✓ x✗ s✓ | c✓ x✗ s✗ |
| restock_cost#10 | c✓ x✓ s✓ | c✓ x✓ s✓ | c✓ x✓ s✓ |

## Faulted-only success (reps 1–10)

Reps 1–10; runs with faults > 0. Wilson 95% CI.

| Condition | Model | Faulted: success / n | 95% CI | No fault fired | of which no draw at all |
|---|---|---:|---|---:|---:|
| chaos | claude-opus-5-5 | 13/58 (22%) | 14%–35% | 2 | 0 |
| chaos | claude-sonnet-5-5 | 13/58 (22%) | 14%–35% | 2 | 0 |
| chaos | claude-haiku-5-5 | 9/58 (16%) | 8%–27% | 2 | 0 |
| chaos_scoped | claude-opus-5-5 | 25/45 (56%) | 41%–69% | 15 | 10 |
| chaos_scoped | claude-sonnet-5-5 | 17/45 (38%) | 25%–52% | 15 | 10 |
| chaos_scoped | claude-haiku-5-5 | 20/45 (44%) | 31%–59% | 15 | 10 |
| chaos_shim | claude-opus-5-5 | 13/58 (22%) | 14%–35% | 2 | 0 |
| chaos_shim | claude-sonnet-5-5 | 12/58 (21%) | 12%–33% | 2 | 0 |
| chaos_shim | claude-haiku-5-5 | 6/58 (10%) | 5%–21% | 2 | 0 |
| chaos_scoped_shim | claude-opus-5-5 | 28/45 (62%) | 48%–75% | 15 | 10 |
| chaos_scoped_shim | claude-sonnet-5-5 | 26/45 (58%) | 43%–71% | 15 | 10 |
| chaos_scoped_shim | claude-haiku-5-5 | 26/45 (58%) | 43%–71% | 15 | 10 |

## Between-model McNemar (reps 1–10)

Reps 1–10, paired on (task, rep). b = A ✓ B ✗, c = A ✗ B ✓; p = exact two-sided McNemar. Bonferroni ×3: family = the 3 model pairs within one condition and scope. Bonferroni ×9: family = 3 pairs × 3 conditions (clean, chaos, chaos_scoped) within one scope. Faulted-only: both runs had faults > 0.

| Condition | Scope | A vs B | Pairs | A ✓ | B ✓ | b | c | p | Bonf ×3 | Bonf ×9 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| clean | all | claude-opus-5-5 vs claude-sonnet-5-5 | 60 | 60 | 60 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| clean | all | claude-opus-5-5 vs claude-haiku-5-5 | 60 | 60 | 60 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| clean | all | claude-sonnet-5-5 vs claude-haiku-5-5 | 60 | 60 | 60 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| clean | faulted-only | claude-opus-5-5 vs claude-sonnet-5-5 | 0 | 0 | 0 | 0 | 0 | - | - | - |
| clean | faulted-only | claude-opus-5-5 vs claude-haiku-5-5 | 0 | 0 | 0 | 0 | 0 | - | - | - |
| clean | faulted-only | claude-sonnet-5-5 vs claude-haiku-5-5 | 0 | 0 | 0 | 0 | 0 | - | - | - |
| chaos | all | claude-opus-5-5 vs claude-sonnet-5-5 | 60 | 15 | 15 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| chaos | all | claude-opus-5-5 vs claude-haiku-5-5 | 60 | 15 | 11 | 4 | 0 | 0.125 | 0.375 | 1.000 |
| chaos | all | claude-sonnet-5-5 vs claude-haiku-5-5 | 60 | 15 | 11 | 4 | 0 | 0.125 | 0.375 | 1.000 |
| chaos | faulted-only | claude-opus-5-5 vs claude-sonnet-5-5 | 58 | 13 | 13 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| chaos | faulted-only | claude-opus-5-5 vs claude-haiku-5-5 | 58 | 13 | 9 | 4 | 0 | 0.125 | 0.375 | 1.000 |
| chaos | faulted-only | claude-sonnet-5-5 vs claude-haiku-5-5 | 58 | 13 | 9 | 4 | 0 | 0.125 | 0.375 | 1.000 |
| chaos_scoped | all | claude-opus-5-5 vs claude-sonnet-5-5 | 60 | 40 | 32 | 8 | 0 | 0.008 | 0.023 | 0.070 |
| chaos_scoped | all | claude-opus-5-5 vs claude-haiku-5-5 | 60 | 40 | 35 | 5 | 0 | 0.062 | 0.188 | 0.562 |
| chaos_scoped | all | claude-sonnet-5-5 vs claude-haiku-5-5 | 60 | 32 | 35 | 1 | 4 | 0.375 | 1.000 | 1.000 |
| chaos_scoped | faulted-only | claude-opus-5-5 vs claude-sonnet-5-5 | 45 | 25 | 17 | 8 | 0 | 0.008 | 0.023 | 0.070 |
| chaos_scoped | faulted-only | claude-opus-5-5 vs claude-haiku-5-5 | 45 | 25 | 20 | 5 | 0 | 0.062 | 0.188 | 0.562 |
| chaos_scoped | faulted-only | claude-sonnet-5-5 vs claude-haiku-5-5 | 45 | 17 | 20 | 1 | 4 | 0.375 | 1.000 | 1.000 |

## Winnable subset

Rule: first_entry != OP4/permanent (null first_entry counts as zero dose and is kept). Reps 1–10 only; extension reps are in their own table (seed-selected, not paper-faithful).

| Model | Condition | Reps 1–10: success (95% CI) |
|---|---|---|
| claude-haiku-5-5 | chaos | 11/23 (48%, 29%–67%) |
| claude-haiku-5-5 | chaos_shim | 8/23 (35%, 19%–55%) |
| claude-opus-5-5 | chaos | 15/23 (65%, 45%–81%) |
| claude-opus-5-5 | chaos_shim | 15/23 (65%, 45%–81%) |
| claude-sonnet-5-5 | chaos | 15/23 (65%, 45%–81%) |
| claude-sonnet-5-5 | chaos_shim | 14/23 (61%, 41%–78%) |

## Resilience shim: pre-registered analysis

| Model | Condition (reps 1–10) | n | Success | 95% CI | Tool calls | Wall time | Timeouts |
|---|---|---:|---:|---|---:|---:|---:|
| claude-haiku-5-5 | clean_shim | 60 | 60 (100%) | 94%–100% | 8.8 | 8s | 0 |
| claude-haiku-5-5 | chaos_shim | 60 | 8 (13%) | 7%–24% | 7.1 | 31s | 0 |
| claude-haiku-5-5 | chaos_scoped_shim | 60 | 41 (68%) | 56%–79% | 9.4 | 20s | 0 |
| claude-opus-5-5 | clean_shim | 60 | 60 (100%) | 94%–100% | 8.2 | 12s | 0 |
| claude-opus-5-5 | chaos_shim | 60 | 15 (25%) | 16%–37% | 8.7 | 40s | 0 |
| claude-opus-5-5 | chaos_scoped_shim | 60 | 43 (72%) | 59%–81% | 9.1 | 24s | 0 |
| claude-sonnet-5-5 | clean_shim | 60 | 60 (100%) | 94%–100% | 8.2 | 14s | 0 |
| claude-sonnet-5-5 | chaos_shim | 60 | 14 (23%) | 14%–35% | 6.8 | 35s | 0 |
| claude-sonnet-5-5 | chaos_scoped_shim | 60 | 41 (68%) | 56%–79% | 8.5 | 25s | 0 |

Reps 1–10, paired on (task, rep). b = shim ✓ no-shim ✗, c = shim ✗ no-shim ✓; p = exact two-sided McNemar; Bonferroni ×3 across models. **Primary (confirmatory): chaos_scoped_shim vs chaos_scoped, pairs whose no-shim run had faults > 0.** The other rows are secondary.

| Comparison | Model | Population | Pairs | No-shim ✓ | Shim ✓ | b | c | p | Bonf ×3 | Median wall no-shim | Median wall shim |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| chaos_scoped_shim vs chaos_scoped (primary) | claude-opus-5-5 | faulted-only (no-shim) | 45 | 25 | 28 | 3 | 0 | 0.250 | 0.750 | 17s | 16s |
| chaos_scoped_shim vs chaos_scoped (primary) | claude-sonnet-5-5 | faulted-only (no-shim) | 45 | 17 | 26 | 10 | 1 | 0.012 | 0.035 | 13s | 15s |
| chaos_scoped_shim vs chaos_scoped (primary) | claude-haiku-5-5 | faulted-only (no-shim) | 45 | 20 | 26 | 6 | 0 | 0.031 | 0.094 | 10s | 11s |
| chaos_shim vs chaos | claude-opus-5-5 | faulted-only (no-shim) | 58 | 13 | 13 | 0 | 0 | 1.000 | 1.000 | 14s | 14s |
| chaos_shim vs chaos | claude-sonnet-5-5 | faulted-only (no-shim) | 58 | 13 | 12 | 0 | 1 | 1.000 | 1.000 | 10s | 12s |
| chaos_shim vs chaos | claude-haiku-5-5 | faulted-only (no-shim) | 58 | 9 | 6 | 1 | 4 | 0.375 | 1.000 | 8s | 8s |
| clean_shim vs clean | claude-opus-5-5 | all pairs | 60 | 60 | 60 | 0 | 0 | 1.000 | 1.000 | 12s | 12s |
| clean_shim vs clean | claude-sonnet-5-5 | all pairs | 60 | 60 | 60 | 0 | 0 | 1.000 | 1.000 | 12s | 13s |
| clean_shim vs clean | claude-haiku-5-5 | all pairs | 60 | 60 | 60 | 0 | 0 | 1.000 | 1.000 | 7s | 8s |

Secondary slices (not confirmatory). First entry and fallback-eligible target (get_price, get_price_v2, get_note, list_notes) are taken from the no-shim run, within the faulted-only population.

| Comparison | Model | Slice | Pairs | No-shim ✓ | Shim ✓ | b | c | p | Median wall no-shim | Median wall shim |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| chaos_scoped_shim vs chaos_scoped | claude-opus-5-5 | first entry OP2/intermittent | 1 | 0 | 1 | 1 | 0 | 1.000 | 266s | 54s |
| chaos_scoped_shim vs chaos_scoped | claude-opus-5-5 | first entry OP2/permanent | 8 | 8 | 8 | 0 | 0 | 1.000 | 19s | 15s |
| chaos_scoped_shim vs chaos_scoped | claude-opus-5-5 | first entry OP3/permanent | 1 | 1 | 1 | 0 | 0 | 1.000 | 16s | 13s |
| chaos_scoped_shim vs chaos_scoped | claude-opus-5-5 | first entry OP4/permanent | 29 | 11 | 13 | 2 | 0 | 0.500 | 16s | 16s |
| chaos_scoped_shim vs chaos_scoped | claude-opus-5-5 | first entry OP4/transient | 1 | 0 | 0 | 0 | 0 | 1.000 | 10s | 17s |
| chaos_scoped_shim vs chaos_scoped | claude-opus-5-5 | first entry OP5/permanent | 1 | 1 | 1 | 0 | 0 | 1.000 | 130s | 130s |
| chaos_scoped_shim vs chaos_scoped | claude-opus-5-5 | first entry OP6/permanent | 4 | 4 | 4 | 0 | 0 | 1.000 | 249s | 149s |
| chaos_scoped_shim vs chaos_scoped | claude-opus-5-5 | target eligible | 20 | 18 | 20 | 2 | 0 | 0.500 | 19s | 17s |
| chaos_scoped_shim vs chaos_scoped | claude-opus-5-5 | target not eligible | 25 | 7 | 8 | 1 | 0 | 1.000 | 16s | 15s |
| chaos_scoped_shim vs chaos_scoped | claude-opus-5-5 | OP4/permanent first draw × fallback-eligible target | 10 | 8 | 10 | 2 | 0 | 0.500 | 16s | 17s |
| chaos_scoped_shim vs chaos_scoped | claude-opus-5-5 | OP4/permanent × no fallback | 19 | 3 | 3 | 0 | 0 | 1.000 | 16s | 14s |
| chaos_scoped_shim vs chaos_scoped | claude-opus-5-5 | both faulted | 45 | 25 | 28 | 3 | 0 | 0.250 | 17s | 16s |
| chaos_scoped_shim vs chaos_scoped | claude-opus-5-5 | all pairs | 60 | 40 | 43 | 3 | 0 | 0.250 | 16s | 15s |
| chaos_scoped_shim vs chaos_scoped | claude-sonnet-5-5 | first entry OP2/intermittent | 1 | 0 | 1 | 1 | 0 | 1.000 | 201s | 56s |
| chaos_scoped_shim vs chaos_scoped | claude-sonnet-5-5 | first entry OP2/permanent | 8 | 7 | 6 | 0 | 1 | 1.000 | 15s | 14s |
| chaos_scoped_shim vs chaos_scoped | claude-sonnet-5-5 | first entry OP3/permanent | 1 | 1 | 1 | 0 | 0 | 1.000 | 10s | 15s |
| chaos_scoped_shim vs chaos_scoped | claude-sonnet-5-5 | first entry OP4/permanent | 29 | 4 | 13 | 9 | 0 | 0.004 | 12s | 15s |
| chaos_scoped_shim vs chaos_scoped | claude-sonnet-5-5 | first entry OP4/transient | 1 | 0 | 0 | 0 | 0 | 1.000 | 14s | 12s |
| chaos_scoped_shim vs chaos_scoped | claude-sonnet-5-5 | first entry OP5/permanent | 1 | 1 | 1 | 0 | 0 | 1.000 | 134s | 134s |
| chaos_scoped_shim vs chaos_scoped | claude-sonnet-5-5 | first entry OP6/permanent | 4 | 4 | 4 | 0 | 0 | 1.000 | 248s | 150s |
| chaos_scoped_shim vs chaos_scoped | claude-sonnet-5-5 | target eligible | 20 | 10 | 18 | 9 | 1 | 0.021 | 14s | 16s |
| chaos_scoped_shim vs chaos_scoped | claude-sonnet-5-5 | target not eligible | 25 | 7 | 8 | 1 | 0 | 1.000 | 13s | 15s |
| chaos_scoped_shim vs chaos_scoped | claude-sonnet-5-5 | OP4/permanent first draw × fallback-eligible target | 10 | 1 | 10 | 9 | 0 | 0.004 | 10s | 18s |
| chaos_scoped_shim vs chaos_scoped | claude-sonnet-5-5 | OP4/permanent × no fallback | 19 | 3 | 3 | 0 | 0 | 1.000 | 12s | 15s |
| chaos_scoped_shim vs chaos_scoped | claude-sonnet-5-5 | both faulted | 45 | 17 | 26 | 10 | 1 | 0.012 | 13s | 15s |
| chaos_scoped_shim vs chaos_scoped | claude-sonnet-5-5 | all pairs | 60 | 32 | 41 | 10 | 1 | 0.012 | 12s | 14s |
| chaos_scoped_shim vs chaos_scoped | claude-haiku-5-5 | first entry OP2/intermittent | 1 | 0 | 0 | 0 | 0 | 1.000 | 317s | 54s |
| chaos_scoped_shim vs chaos_scoped | claude-haiku-5-5 | first entry OP2/permanent | 8 | 6 | 7 | 1 | 0 | 1.000 | 12s | 11s |
| chaos_scoped_shim vs chaos_scoped | claude-haiku-5-5 | first entry OP3/permanent | 1 | 1 | 1 | 0 | 0 | 1.000 | 8s | 9s |
| chaos_scoped_shim vs chaos_scoped | claude-haiku-5-5 | first entry OP4/permanent | 29 | 8 | 13 | 5 | 0 | 0.062 | 9s | 10s |
| chaos_scoped_shim vs chaos_scoped | claude-haiku-5-5 | first entry OP4/transient | 1 | 0 | 0 | 0 | 0 | 1.000 | 9s | 7s |
| chaos_scoped_shim vs chaos_scoped | claude-haiku-5-5 | first entry OP5/permanent | 1 | 1 | 1 | 0 | 0 | 1.000 | 128s | 129s |
| chaos_scoped_shim vs chaos_scoped | claude-haiku-5-5 | first entry OP6/permanent | 4 | 4 | 4 | 0 | 0 | 1.000 | 246s | 146s |
| chaos_scoped_shim vs chaos_scoped | claude-haiku-5-5 | target eligible | 20 | 13 | 19 | 6 | 0 | 0.031 | 12s | 12s |
| chaos_scoped_shim vs chaos_scoped | claude-haiku-5-5 | target not eligible | 25 | 7 | 7 | 0 | 0 | 1.000 | 9s | 10s |
| chaos_scoped_shim vs chaos_scoped | claude-haiku-5-5 | OP4/permanent first draw × fallback-eligible target | 10 | 5 | 10 | 5 | 0 | 0.062 | 11s | 12s |
| chaos_scoped_shim vs chaos_scoped | claude-haiku-5-5 | OP4/permanent × no fallback | 19 | 3 | 3 | 0 | 0 | 1.000 | 9s | 10s |
| chaos_scoped_shim vs chaos_scoped | claude-haiku-5-5 | both faulted | 45 | 20 | 26 | 6 | 0 | 0.031 | 10s | 11s |
| chaos_scoped_shim vs chaos_scoped | claude-haiku-5-5 | all pairs | 60 | 35 | 41 | 6 | 0 | 0.031 | 9s | 10s |
| chaos_shim vs chaos | claude-opus-5-5 | first entry OP2/intermittent | 1 | 0 | 0 | 0 | 0 | 1.000 | 600s | 300s |
| chaos_shim vs chaos | claude-opus-5-5 | first entry OP2/permanent | 10 | 10 | 10 | 0 | 0 | 1.000 | 25s | 29s |
| chaos_shim vs chaos | claude-opus-5-5 | first entry OP3/permanent | 1 | 1 | 1 | 0 | 0 | 1.000 | 14s | 14s |
| chaos_shim vs chaos | claude-opus-5-5 | first entry OP4/intermittent | 2 | 1 | 1 | 0 | 0 | 1.000 | 33s | 21s |
| chaos_shim vs chaos | claude-opus-5-5 | first entry OP4/permanent | 37 | 0 | 0 | 0 | 0 | 1.000 | 12s | 12s |
| chaos_shim vs chaos | claude-opus-5-5 | first entry OP4/transient | 1 | 0 | 0 | 0 | 0 | 1.000 | 12s | 8s |
| chaos_shim vs chaos | claude-opus-5-5 | first entry OP5/intermittent | 1 | 0 | 0 | 0 | 0 | 1.000 | 17s | 16s |
| chaos_shim vs chaos | claude-opus-5-5 | first entry OP5/permanent | 1 | 1 | 1 | 0 | 0 | 1.000 | 340s | 342s |
| chaos_shim vs chaos | claude-opus-5-5 | first entry OP6/permanent | 4 | 0 | 0 | 0 | 0 | 1.000 | 456s | 238s |
| chaos_shim vs chaos | claude-opus-5-5 | both faulted | 58 | 13 | 13 | 0 | 0 | 1.000 | 14s | 14s |
| chaos_shim vs chaos | claude-opus-5-5 | all pairs | 60 | 15 | 15 | 0 | 0 | 1.000 | 14s | 14s |
| chaos_shim vs chaos | claude-sonnet-5-5 | first entry OP2/intermittent | 1 | 0 | 0 | 0 | 0 | 1.000 | 600s | 263s |
| chaos_shim vs chaos | claude-sonnet-5-5 | first entry OP2/permanent | 10 | 10 | 9 | 0 | 1 | 1.000 | 16s | 20s |
| chaos_shim vs chaos | claude-sonnet-5-5 | first entry OP3/permanent | 1 | 1 | 1 | 0 | 0 | 1.000 | 21s | 14s |
| chaos_shim vs chaos | claude-sonnet-5-5 | first entry OP4/intermittent | 2 | 1 | 1 | 0 | 0 | 1.000 | 32s | 16s |
| chaos_shim vs chaos | claude-sonnet-5-5 | first entry OP4/permanent | 37 | 0 | 0 | 0 | 0 | 1.000 | 8s | 10s |
| chaos_shim vs chaos | claude-sonnet-5-5 | first entry OP4/transient | 1 | 0 | 0 | 0 | 0 | 1.000 | 8s | 7s |
| chaos_shim vs chaos | claude-sonnet-5-5 | first entry OP5/intermittent | 1 | 0 | 0 | 0 | 0 | 1.000 | 11s | 20s |
| chaos_shim vs chaos | claude-sonnet-5-5 | first entry OP5/permanent | 1 | 1 | 1 | 0 | 0 | 1.000 | 346s | 349s |
| chaos_shim vs chaos | claude-sonnet-5-5 | first entry OP6/permanent | 4 | 0 | 0 | 0 | 0 | 1.000 | 399s | 204s |
| chaos_shim vs chaos | claude-sonnet-5-5 | both faulted | 58 | 13 | 12 | 0 | 1 | 1.000 | 10s | 12s |
| chaos_shim vs chaos | claude-sonnet-5-5 | all pairs | 60 | 15 | 14 | 0 | 1 | 1.000 | 10s | 12s |
| chaos_shim vs chaos | claude-haiku-5-5 | first entry OP2/intermittent | 1 | 0 | 0 | 0 | 0 | 1.000 | 600s | 259s |
| chaos_shim vs chaos | claude-haiku-5-5 | first entry OP2/permanent | 10 | 6 | 3 | 1 | 4 | 0.375 | 14s | 13s |
| chaos_shim vs chaos | claude-haiku-5-5 | first entry OP3/permanent | 1 | 1 | 1 | 0 | 0 | 1.000 | 10s | 9s |
| chaos_shim vs chaos | claude-haiku-5-5 | first entry OP4/intermittent | 2 | 1 | 1 | 0 | 0 | 1.000 | 21s | 18s |
| chaos_shim vs chaos | claude-haiku-5-5 | first entry OP4/permanent | 37 | 0 | 0 | 0 | 0 | 1.000 | 7s | 8s |
| chaos_shim vs chaos | claude-haiku-5-5 | first entry OP4/transient | 1 | 0 | 0 | 0 | 0 | 1.000 | 7s | 7s |
| chaos_shim vs chaos | claude-haiku-5-5 | first entry OP5/intermittent | 1 | 0 | 0 | 0 | 0 | 1.000 | 11s | 12s |
| chaos_shim vs chaos | claude-haiku-5-5 | first entry OP5/permanent | 1 | 1 | 1 | 0 | 0 | 1.000 | 338s | 338s |
| chaos_shim vs chaos | claude-haiku-5-5 | first entry OP6/permanent | 4 | 0 | 0 | 0 | 0 | 1.000 | 399s | 200s |
| chaos_shim vs chaos | claude-haiku-5-5 | both faulted | 58 | 9 | 6 | 1 | 4 | 0.375 | 8s | 8s |
| chaos_shim vs chaos | claude-haiku-5-5 | all pairs | 60 | 11 | 8 | 1 | 4 | 0.375 | 8s | 8s |

## After an error on the target (faulted one-tool pairs)

| Model | Arm | Faulted pairs | Runs repeating a target call (same args) | Runs retrying after an error | Retry calls (any tool) | Target errored | Stopped (succ.) | Fallback (succ.) | Retried (succ.) | Both (succ.) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| claude-opus-5-5 | no shim | 45 | 9 | 5 | 7 | 35 | 19 (4) | 11 (10) | 4 (0) | 1 (1) |
| claude-opus-5-5 | shim | 45 | 3 | 0 | 0 | 35 | 22 (5) | 13 (13) | 0 (0) | 0 (0) |
| claude-sonnet-5-5 | no shim | 45 | 3 | 1 | 2 | 35 | 30 (4) | 4 (4) | 1 (0) | 0 (0) |
| claude-sonnet-5-5 | shim | 45 | 2 | 0 | 0 | 35 | 22 (5) | 13 (13) | 0 (0) | 0 (0) |
| claude-haiku-5-5 | no shim | 45 | 14 | 12 | 18 | 35 | 17 (2) | 6 (6) | 5 (2) | 7 (2) |
| claude-haiku-5-5 | shim | 45 | 4 | 0 | 0 | 35 | 22 (4) | 13 (13) | 0 (0) | 0 (0) |

OP4/permanent first draw × fallback-eligible target (the pre-registered slice; first entry and target taken from the no-shim run; targets get_price, get_price_v2, get_note, list_notes):

| Model | Arm | Runs | Target errored | Stopped (succ.) | Fallback (succ.) | Retried (succ.) | Both (succ.) |
|---|---|---:|---:|---:|---:|---:|---:|
| claude-opus-5-5 | no shim | 10 | 10 | 1 (0) | 8 (7) | 0 (0) | 1 (1) |
| claude-opus-5-5 | shim | 10 | 10 | 0 (0) | 10 (10) | 0 (0) | 0 (0) |
| claude-sonnet-5-5 | no shim | 10 | 10 | 9 (0) | 1 (1) | 0 (0) | 0 (0) |
| claude-sonnet-5-5 | shim | 10 | 10 | 0 (0) | 10 (10) | 0 (0) | 0 (0) |
| claude-haiku-5-5 | no shim | 10 | 10 | 0 (0) | 4 (4) | 0 (0) | 6 (1) |
| claude-haiku-5-5 | shim | 10 | 10 | 0 (0) | 10 (10) | 0 (0) | 0 (0) |

## Extension: winnable reps (seed-selected, not paper-faithful)

Extension reps come from `bench/winnable_reps.json`: (task, rep) pairs chosen because their first draw is not OP4/permanent. They are seed-selected, not paper-faithful, and never enter the reps 1–10 tables above.

| Model | Condition | Extension reps only (seed-selected, not paper-faithful): success (95% CI) | All reps incl. extension (seed-selected, not paper-faithful): success (95% CI) |
|---|---|---|---|
| claude-haiku-5-5 | chaos | 13/24 (54%, 35%–72%) | 24/47 (51%, 37%–65%) |
| claude-opus-5-5 | chaos | 16/24 (67%, 47%–82%) | 31/47 (66%, 52%–78%) |
| claude-sonnet-5-5 | chaos | 15/24 (62%, 43%–79%) | 30/47 (64%, 50%–76%) |

Shim lift on all paired reps incl. extension (seed-selected, not paper-faithful); improved = base ✗ → shim ✓, worsened = base ✓ → shim ✗; p = exact two-sided sign test.

| Comparison | Model | Reps (seed-selected, not paper-faithful) | Pairs | Base | Shim | Lift | Improved | Worsened | p |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| chaos_shim - chaos | claude-haiku-5-5 | all incl. extension (seed-selected, not paper-faithful) | 60 | 11 | 8 | -5% | 1 | 4 | 0.375 |
| chaos_shim - chaos | claude-opus-5-5 | all incl. extension (seed-selected, not paper-faithful) | 60 | 15 | 15 | +0% | 0 | 0 | 1.000 |
| chaos_shim - chaos | claude-sonnet-5-5 | all incl. extension (seed-selected, not paper-faithful) | 60 | 15 | 14 | -2% | 0 | 1 | 1.000 |
| chaos_scoped_shim - chaos_scoped | claude-haiku-5-5 | all incl. extension (seed-selected, not paper-faithful) | 60 | 35 | 41 | +10% | 6 | 0 | 0.031 |
| chaos_scoped_shim - chaos_scoped | claude-opus-5-5 | all incl. extension (seed-selected, not paper-faithful) | 60 | 40 | 43 | +5% | 3 | 0 | 0.250 |
| chaos_scoped_shim - chaos_scoped | claude-sonnet-5-5 | all incl. extension (seed-selected, not paper-faithful) | 60 | 32 | 41 | +15% | 10 | 1 | 0.012 |
| clean_shim - clean | claude-haiku-5-5 | all incl. extension (seed-selected, not paper-faithful) | 60 | 60 | 60 | +0% | 0 | 0 | 1.000 |
| clean_shim - clean | claude-opus-5-5 | all incl. extension (seed-selected, not paper-faithful) | 60 | 60 | 60 | +0% | 0 | 0 | 1.000 |
| clean_shim - clean | claude-sonnet-5-5 | all incl. extension (seed-selected, not paper-faithful) | 60 | 60 | 60 | +0% | 0 | 0 | 1.000 |

#### chaos_shim - chaos: lift by first drawn entry, all paired reps incl. extension (seed-selected, not paper-faithful) (base→shim successes / pairs)

| First entry (seed-selected, not paper-faithful) | claude-haiku-5-5 | claude-opus-5-5 | claude-sonnet-5-5 |
|---|---:|---:|---:|
| OP2/intermittent | 0→0/1 | 0→0/1 | 0→0/1 |
| OP2/permanent | 6→3/10 | 10→10/10 | 10→9/10 |
| OP3/permanent | 1→1/1 | 1→1/1 | 1→1/1 |
| OP4/intermittent | 3→3/4 | 3→3/4 | 3→3/4 |
| OP4/permanent | 0→0/37 | 0→0/37 | 0→0/37 |
| OP4/transient | 0→0/1 | 0→0/1 | 0→0/1 |
| OP5/intermittent | 0→0/1 | 0→0/1 | 0→0/1 |
| OP5/permanent | 1→1/1 | 1→1/1 | 1→1/1 |
| OP6/permanent | 0→0/4 | 0→0/4 | 0→0/4 |

#### chaos_scoped_shim - chaos_scoped: lift by first drawn entry, all paired reps incl. extension (seed-selected, not paper-faithful) (base→shim successes / pairs)

| First entry (seed-selected, not paper-faithful) | claude-haiku-5-5 | claude-opus-5-5 | claude-sonnet-5-5 |
|---|---:|---:|---:|
| OP2/intermittent | 0→0/1 | 0→1/1 | 0→1/1 |
| OP2/permanent | 6→7/8 | 8→8/8 | 7→6/8 |
| OP3/permanent | 1→1/1 | 1→1/1 | 1→1/1 |
| OP4/intermittent | 4→4/4 | 4→4/4 | 4→4/4 |
| OP4/permanent | 8→13/29 | 11→13/29 | 4→13/29 |
| OP4/transient | 0→0/1 | 0→0/1 | 0→0/1 |
| OP5/intermittent | 1→1/1 | 1→1/1 | 1→1/1 |
| OP5/permanent | 1→1/1 | 1→1/1 | 1→1/1 |
| OP6/permanent | 4→4/4 | 4→4/4 | 4→4/4 |
| no draw | 10→10/10 | 10→10/10 | 10→10/10 |

#### clean_shim - clean: lift by first drawn entry, all paired reps incl. extension (seed-selected, not paper-faithful) (base→shim successes / pairs)

| First entry (seed-selected, not paper-faithful) | claude-haiku-5-5 | claude-opus-5-5 | claude-sonnet-5-5 |
|---|---:|---:|---:|
| no draw | 60→60/60 | 60→60/60 | 60→60/60 |

## Run caps

| Model | Condition | Runs | Hit cap | Run cap (s) |
|---|---|---:|---:|---|
| claude-haiku-5-5 | clean | 60 | 0 | 600 |
| claude-haiku-5-5 | chaos | 84 | 4 | 600 |
| claude-haiku-5-5 | chaos_scoped | 60 | 0 | 600 |
| claude-haiku-5-5 | clean_shim | 60 | 0 | 600 |
| claude-haiku-5-5 | chaos_shim | 60 | 0 | 600 |
| claude-haiku-5-5 | chaos_scoped_shim | 60 | 0 | 600 |
| claude-haiku-5-5 | chaos_cap3000 | 5 | 0 | 3000 |
| claude-opus-5-5 | clean | 60 | 0 | 600 |
| claude-opus-5-5 | chaos | 84 | 7 | 600 |
| claude-opus-5-5 | chaos_scoped | 60 | 0 | 600 |
| claude-opus-5-5 | clean_shim | 60 | 0 | 600 |
| claude-opus-5-5 | chaos_shim | 60 | 0 | 600 |
| claude-opus-5-5 | chaos_scoped_shim | 60 | 0 | 600 |
| claude-opus-5-5 | chaos_cap3000 | 7 | 0 | 3000 |
| claude-sonnet-5-5 | clean | 60 | 0 | 600 |
| claude-sonnet-5-5 | chaos | 84 | 2 | 600 |
| claude-sonnet-5-5 | chaos_scoped | 60 | 0 | 600 |
| claude-sonnet-5-5 | clean_shim | 60 | 0 | 600 |
| claude-sonnet-5-5 | chaos_shim | 60 | 0 | 600 |
| claude-sonnet-5-5 | chaos_scoped_shim | 60 | 0 | 600 |
| claude-sonnet-5-5 | chaos_cap3000 | 4 | 0 | 3000 |

Cap sensitivity: chaos_cap3000 (3000 s cap) vs the same (task, model, rep) in chaos (600 s cap).

| Model | Pairs | chaos ok | cap3000 ok | chaos hit cap | cap3000 hit cap | → success | → failure | Mean wall chaos | Mean wall cap3000 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| claude-haiku-5-5 | 5 | 0 | 0 | 4 | 0 | 0 | 0 | 590s | 683s |
| claude-opus-5-5 | 7 | 0 | 0 | 7 | 0 | 0 | 0 | 600s | 711s |
| claude-sonnet-5-5 | 4 | 0 | 0 | 2 | 0 | 0 | 0 | 544s | 612s |

| Task | Model | Rep | chaos outcome | chaos wall | cap3000 outcome | cap3000 wall |
|---|---|---:|---|---:|---|---:|
| cheapest_in_stock_order | claude-haiku-5-5 | 15 | timeout | 600s | fail | 972s |
| price_total | claude-haiku-5-5 | 1 | timeout | 600s | fail | 549s |
| price_total | claude-haiku-5-5 | 10 | fail | 549s | fail | 550s |
| price_total | claude-haiku-5-5 | 18 | timeout | 600s | fail | 487s |
| restock_cost | claude-haiku-5-5 | 2 | timeout | 600s | fail | 856s |
| budget_order | claude-opus-5-5 | 22 | timeout | 600s | fail | 552s |
| cheapest_in_stock_order | claude-opus-5-5 | 15 | timeout | 600s | fail | 1046s |
| price_total | claude-opus-5-5 | 1 | timeout | 600s | fail | 611s |
| price_total | claude-opus-5-5 | 10 | timeout | 600s | fail | 612s |
| price_total | claude-opus-5-5 | 18 | timeout | 600s | fail | 613s |
| restock_cost | claude-opus-5-5 | 2 | timeout | 600s | fail | 920s |
| restock_cost | claude-opus-5-5 | 21 | timeout | 600s | fail | 623s |
| cheapest_in_stock_order | claude-sonnet-5-5 | 15 | timeout | 600s | fail | 794s |
| price_total | claude-sonnet-5-5 | 1 | fail | 487s | fail | 493s |
| price_total | claude-sonnet-5-5 | 10 | fail | 488s | fail | 487s |
| restock_cost | claude-sonnet-5-5 | 2 | timeout | 600s | fail | 672s |
