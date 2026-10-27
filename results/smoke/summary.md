# Smoke run (harness wiring check)

One arena cell: `--models claude-haiku-5-5 --tasks note_summary --conditions chaos_scoped --reps 1`.

| Model | Condition | n | Success | 95% CI | Tool calls | Retries | Faults fired | Wall time | Timeouts | Built-in tool runs |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| claude-haiku-5-5 | chaos_scoped | 1 | 0 (0%) | 0%–79% | 6.0 | 4.00 | 4.00 | 10s | 0 | 0 |

| Model | Effort | Resilience (chaos ÷ clean) | Scoped resilience (chaos_scoped ÷ clean) | Models seen |
|---|---|---:|---:|---|
| claude-haiku-5-5 | medium | n/a | n/a | claude-haiku-5-5 |

### Coverage (successes / runs per task)

| Model | Task | chaos_scoped |
|---|---|---:|
| claude-haiku-5-5 | note_summary | 0/1 |

### chaos_scoped: success by first drawn entry

| First entry | claude-haiku-5-5 |
|---|---:|
| OP4/permanent | 0/1 |

### Models used (from Claude Code modelUsage)

| Model id | Runs | Input tokens | Output tokens | Cache read | Cache write | Cost (USD) |
|---|---:|---:|---:|---:|---:|---:|
| claude-haiku-5-5 | 1 | 10 | 861 | 18,841 | 5,133 | 0.00 |
