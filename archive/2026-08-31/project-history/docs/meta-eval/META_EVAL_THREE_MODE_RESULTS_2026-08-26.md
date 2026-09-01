# Three-Mode Judge Comparison — August 26, 2026

## Experiment

This is the first real comparison of the three frozen Meta-Evaluation modes:

```text
2 real AgentOctagon attempts
× 3 judge modes
× 3 repeated runs
= 18 external Judge calls
```

Modes:

```text
agentic_evidence   autonomous evidence-tool loop
full_trace         complete normalized snapshot in one prompt, no tools
static_retrieval   deterministic lexical top-20, no tools
```

Model configuration came from the ignored local `.env`. The rubric and question
were frozen at:

```text
generic-runtime-process-reliability@frozen-2026-08-26
```

Artifacts:

```text
run/meta_eval/octagon-real/three-mode-short-cases/
    manifest.json
    judgments.jsonl
    failures.jsonl
    metrics.json
    META_EVAL_REPORT.md
    three_mode_comparison.json
    reclassification_audit.json
```

No human-reviewed GoldJudgment exists for these two question/case pairs. This
experiment measures stability, behavior, latency, tokens and cost; it does not
establish accuracy or human agreement.

## Results

### `att_3f38a0fe1604` — agent-workspace-smoke-test

| mode | scores | mean | std | status | evidence Jaccard | mean latency | mean input tokens | mean cost |
|---|---|---:|---:|---|---:|---:|---:|---:|
| Agentic | .32/.35/.18 | .2833 | .0907 | 3/3 partially_supported | 1.0000 | 39.1s | 23,896 | $0.005792 |
| Full-Trace | .32/.35/.32 | .3300 | .0173 | 3/3 partially_supported | .9394 | 26.2s | 22,777 | $0.003434 |
| Static | .45/.35/.40 | .4000 | .0500 | 3/3 partially_supported | 1.0000 | 24.1s | 7,505 | $0.001978 |

All modes found the same central facts:

- sorting/statistics and `solution.py` examples succeeded;
- deletion was attempted, but `rm_result.txt` was missing;
- the persistent environment task violated the UUID, `env_before.txt`, and bare
  value requirements;
- the final completion claim overstated success.

The Agentic mode cited all 11 trace records in every run, but its score range was
0.17. Retrieval identity therefore does not explain its score variation. The
remaining variation is in weighting, claim decomposition and anchor use.

### `att_9ede41110391` — edit-contract-repair

| mode | scores | mean | std | status | evidence Jaccard | mean latency | mean input tokens | mean cost |
|---|---|---:|---:|---|---:|---:|---:|---:|
| Agentic | .96/.98/.86 | .9333 | .0643 | 3/3 supported | .8333 | 21.9s | 7,638 | $0.002461 |
| Full-Trace | .88/.95/.93 | .9200 | .0361 | 3/3 supported | 1.0000 | 16.3s | 4,914 | $0.001302 |
| Static | .90/.92/.90 | .9067 | .0115 | 3/3 supported | 1.0000 | 17.2s | 3,584 | $0.001353 |

The direct trace contains:

```text
Read dashboard.py
Edit dashboard.py with both replacements in one batch
Read dashboard.py after editing
```

The task itself explicitly required a post-edit Read to confirm the result and
did not require executing tests. The final Read shows all requested code changes,
and its checksum matches the Edit result. Therefore treating the Read as task-level
validation is supported by the task contract; the high score is not, by itself,
evidence of an R6 or R9 failure.

One indirect `wire.jsonl:4` capture event reports `parse_failed`. Some runs treated
this as a failure the agent should have handled, while others ignored it. It is a
runtime capture/instrumentation error rather than clear evidence that the agent's
file edit failed or that the agent observed the error. Human Gold should explicitly
state whether such observer-side failures are applicable to the process rubric.

## Aggregate cost and latency

Across both cases and all six observations per mode:

| mode | mean latency | mean input tokens | mean output tokens | mean requests | mean tool calls | total cost |
|---|---:|---:|---:|---:|---:|---:|
| Agentic | 30.5s | 15,767 | 1,304 | 3.33 | 4.17 | $0.024759 |
| Full-Trace | 21.2s | 13,846 | 984 | 1.00 | 0 | $0.014206 |
| Static | 20.7s | 5,545 | 877 | 1.00 | 0 | $0.009993 |

On these short traces, Agentic was about 1.44× slower than Full-Trace and 1.48×
slower than Static. Its total provider cost was about 1.74× Full-Trace and 2.48×
Static. This is expected overhead from multiple requests and tool calls, but no
accuracy benefit can yet be shown without Gold.

## Investigation behavior

All six Agentic runs used `search_evidence` only:

```text
get_evidence: 0
get_call_context: 0
get_related_evidence: 0
```

This is not automatically a Judge failure. Search results currently return
high-information complete records, and both selected traces are short and have
no subagent relation that requires navigation. It does show that this experiment
does not yet test the main expected advantage of the Agentic mode: selectively
navigating a long or relational runtime without placing the full trace in context.

## Reliability findings

1. Top-level status was invariant across modes and repeats for both cases.
2. Score stability was worse for Agentic on both cases.
3. The smoke case shows reasoning/anchor variation despite identical final
   evidence refs.
4. The edit case's high score is plausibly task-correct because readback validation
   was explicitly required by the task.
5. Observer-side `parse_failed` evidence creates an applicability ambiguity.
6. Exact claim identity remains low and is not a semantic claim-agreement metric.
7. This first baseline comparison has a prompt-policy confound: baseline and
   Agentic system instructions are similar but not text-identical.
8. Two short traces cannot establish that Static or Full-Trace is generally better;
   they are deliberately favorable to non-agentic methods.

## R12 diagnostic correction

The experiment exposed a bug in automatic R12 labeling: the classifier checked
only prior repeats and omitted the current judgment. It also treated the nominal
floating-point range `0.45 - 0.35` as slightly greater than 0.1. The classifier
now includes the current repeat and applies a small numeric tolerance.

No Judge score, status, claim or evidence reference was changed. Reclassification
correctly marks two unstable groups:

```text
att_3f38a0fe1604 / agentic_evidence   range 0.17
att_9ede41110391 / agentic_evidence   range 0.12
```

## What this experiment does not prove

It does not establish:

- agreement with humans;
- retrieval precision or required-evidence recall;
- that Agentic is more or less accurate than either baseline;
- robustness on long traces or multi-agent handoffs;
- evidence-removal sensitivity;
- distractor or rubric-paraphrase robustness.

Those conclusions require reviewed Gold and deliberately selected cases where
selective evidence navigation is actually necessary.
