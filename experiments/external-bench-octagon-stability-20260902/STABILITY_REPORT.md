# 4-task exploratory stability analysis

- Date: 2026-09-02
- Runner: `/home/yang/agent-octagon`
- 4 retained tasks × 3 repeats × 3 agents = 36 attempt slots
- Parallel topology: each task/repeat run used `execution=parallel`, so three agents were started concurrently within that task.
- Shared model identity: `deepseek/deepseek-v4-flash-0731`
- Scorer: `external-octagon-scorer-v1`

## Scores by repeat

| Task | Agent | R1 | R2 | R3 | mean | population SD | status pattern |
|---|---|---:|---:|---:|---:|---:|---|
| AgencyBench 2 repo-review | claude-code | 40 | 100 | 8 | 49.33 | 38.13 | gave_up / completed / gave_up |
|  | codex | 40 | 40 | 40 | 40.00 | 0.00 | gave_up / gave_up / gave_up |
|  | blade-agent | 32 | 100 | 100 | 77.33 | 32.06 | gave_up / completed / completed |
| AgencyBench 3 event-generator | claude-code | 40 | 40 | 40 | 40.00 | 0.00 | gave_up / gave_up / gave_up |
|  | codex | 40 | 15 | 40 | 31.67 | 11.79 | gave_up / gave_up / gave_up |
|  | blade-agent | 40 | 40 | 40 | 40.00 | 0.00 | gave_up / gave_up / gave_up |
| DEVAI 52 qlora | claude-code | 85 | 85 | 92 | 87.33 | 3.30 | completed / completed / completed |
|  | codex | 85 | 40 | 85 | 70.00 | 21.21 | completed / gave_up / completed |
|  | blade-agent | 62 | 70 | — | 66.00* | 4.00* | timeout / completed / completed |
| DEVAI 54 response-analyzer | claude-code | 100 | 100 | 100 | 100.00 | 0.00 | completed / completed / completed |
|  | codex | 100 | 62 | 100 | 87.33 | 17.91 | completed / completed / completed |
|  | blade-agent | 100 | — | — | 100.00* | — | completed / interrupted / interrupted |

`*` mean/SD use available scored repeats only; missing attempts are not imputed.

## Interpretation

### AgencyBench 2 — not a stable agent capability separation

There is a large mean gap (`blade 77.33 > claude 49.33 > codex 40`), but Claude and Blade vary by 60–92 points between repeats. The ordering is therefore not stable enough to call a systematic capability difference. Codex is stable at a low score, but the task's overall execution success is poor, so this is better treated as a robustness/termination signal than a clean capability measure.

### AgencyBench 3 — no useful discrimination

Claude and Blade are exactly 40 in all three repeats; Codex is 40/15/40. This is a scorer/ceiling-or-floor style collapse rather than a reproducible three-agent separation. The task should be excluded from later formal comparison, even though it was retained for this exploratory check.

### DEVAI 52 — strongest evidence for a systematic difference

Claude is high and stable (`85,85,92`, SD 3.30). Blade is consistently lower on its two completed repeats (`62,70`) and had one timeout. Codex is usually high (`85,85`) but has one gave-up outlier (`40`). The most defensible conclusion is: **Claude's advantage over Blade is plausibly systematic for this task's artifact requirements; Codex is inconclusive because of one execution outlier.** This remains exploratory because the scorer is structural and the repetition count is only three.

### DEVAI 54 — ceiling effect, no reliable capability separation

Claude scores 100 in every repeat. Blade also scores 100 on its only completed repeat. Codex scores 100 twice and 62 once. The task has a strong ceiling effect; successful runs do not distinguish the agents. The Codex low repeat is more consistent with an execution/path outlier than a stable capability gap.

## Decision

- Keep **DEVAI 52** as the best candidate for a follow-up systematic capability comparison.
- Keep **AgencyBench 2** only as an execution-variance/robustness example; do not interpret its single-run ordering as a capability ranking.
- Remove **AgencyBench 3** from future formal comparisons because it has no useful discrimination.
- Remove **DEVAI 54** from future formal comparisons unless its scorer is made more granular to reduce the 100-point ceiling effect.

Raw submission and status artifacts:

- `experiment_manifest.json`
- `submitted_runs.json`
- `run_status.json`
