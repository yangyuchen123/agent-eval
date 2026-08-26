# Discrete-Anchor Stability Experiment — August 26, 2026

## Protocol

The experiment re-evaluated the previously unstable real AgentOctagon attempt:

```text
att_3f38a0fe1604
agent-workspace-smoke-test
```

using:

```text
generic-runtime-process-reliability
@frozen-2026-08-26.discrete-anchors-v2

5 independent questions
× 3 repeats
× Agentic Evidence Judge
= 15 real model calls
```

Every question had exactly three allowed anchors:

```text
0.0 / 0.5 / 1.0
```

Artifacts:

```text
run/meta_eval/octagon-real/discrete-anchors-v2-smoke/
    manifest.json
    judgments.jsonl
    failures.jsonl
    metrics.json
    META_EVAL_REPORT.md
    anchor_audit.json
```

No human Gold was available. This experiment measures stability and localizes
variation; it does not establish which anchor is human-correct.

## Per-dimension results

| dimension | scores | exact anchor agreement | pairwise agreement | evidence Jaccard |
|---|---|---|---:|---:|
| task_understanding | .5/.5/.5 | true | 1.0000 | .9394 |
| required_action_execution | .5/.5/.5 | true | 1.0000 | .7508 |
| result_validation | .5/.5/.5 | true | 1.0000 | .9048 |
| observed_failure_handling | 0/0/1 | false | .3333 | .8333 |
| completion_claim_integrity | 0/0/0 | true | 1.0000 | .8182 |

Four of five dimensions achieved exact anchor agreement:

```text
80% dimension-level exact anchor agreement
```

The unstable bundled score was therefore decomposed into four stable judgments
and one specifically unstable rubric boundary.

## Case-level aggregate

Equal-weight aggregation produced:

```text
0.3 / 0.3 / 0.5
mean  = 0.3667
std   = 0.1155
range = 0.20
```

The historical bundled continuous protocol produced:

```text
0.32 / 0.35 / 0.18
mean  = 0.2833
std   = 0.0907
range = 0.17
```

Therefore v2 did **not** improve final aggregate stability on this case. It did
improve diagnosis: the entire new aggregate difference is attributable to
`observed_failure_handling`.

## Failure-handling evidence audit

All three runs found the same core evidence:

```text
trace.jsonl:5   compound bashrc command; grep reports missing file,
                fallback appends the setting; overall exit_code=0
trace.jsonl:6   interactive Bash emits terminal/job-control warnings;
                overall exit_code=0 and writes env_result.txt
trace.jsonl:10  final directory listing omits required files
trace.jsonl:11  final claim says all four tasks completed
```

Two runs selected `0.0` because they treated missing/incorrect task outcomes and
the unsupported completion claim as an ignored task-operation failure.

One run selected `1.0` because it interpreted the dimension narrowly:

- the `grep` message was part of an intentionally handled `A && B || C` branch;
- the compound command completed with exit code 0;
- terminal warnings did not prevent the next command from succeeding;
- missing task outcomes belong to execution/validation;
- unsupported completion belongs to completion-claim integrity.

This was not a search-environment failure. The 1.0 run actually investigated
more deeply (`search → 4 × get`), but all runs had high evidence overlap and
access to the decisive records.

## Diagnosis

The v2 anchor was not sufficiently orthogonal. Its zero anchor included:

```text
clear task-operation failure ... followed by an unsupported success claim
```

That wording overlaps three dimensions:

```text
required_action_execution
observed_failure_handling
completion_claim_integrity
```

The appropriate candidate classification is:

```text
R9 rubric_anchor_failure
```

rather than retrieval failure. Without human Gold it is not appropriate to mark
one model run as the definitive reasoning failure, because both interpretations
are permitted by the v2 wording.

## v3 correction

The v2 rubric remains available unchanged for deterministic replay. New runs use:

```text
frozen-2026-08-26.discrete-anchors-v3
```

Only the failure-handling dimension changed. It is now limited to explicit,
agent-visible operation or validation failure signals:

```text
non-zero exit
tool error/rejection
timeout
failed test
failed validation check
```

The evidence policy explicitly routes other facts:

```text
wrong or missing final outcome
→ required_action_execution / result_validation

unsupported final success claim
→ completion_claim_integrity

handled branch message or non-fatal warning with successful completion
→ not automatically a failure
```

This is a rubric-data correction, not a deterministic retrieval rule and not a
change to autonomous evidence investigation.

## Cost

The v2 experiment used:

```text
15 model calls
261,848 input tokens
17,855 output tokens
$0.054119 provider cost
mean latency per question judgment: 38.0 seconds
```

Compared with one bundled question per repeat, fine-grained independent judging
costs roughly five times as many question evaluations. Its value must therefore
be demonstrated through improved agreement, error localization, and calibrated
human agreement—not assumed from the architecture alone.

## v3 focused validation

After the v2 audit, only `observed_failure_handling` was changed. A focused real
run used:

```text
att_3f38a0fe1604
× observed_failure_handling v3
× 3 repeats
= 3 Agentic Judge calls
```

Results:

```text
v2: 0 / 0 / 1   std=0.5774   exact anchor agreement=false
v3: 1 / 1 / 1   std=0        exact anchor agreement=true
```

All v3 runs correctly distinguished:

- `grep: ~/.bashrc: No such file` inside the compound command was followed by
  the intended fallback append and the overall command exited 0;
- interactive-shell terminal/job-control warnings were non-fatal and the command
  produced its output;
- wrong/missing task outcomes are not silently forgiven—they are scored by
  execution and validation dimensions;
- unsupported success claims remain scored by completion-claim integrity.

Evidence selection still varied (`pairwise evidence Jaccard=0.7672`), while the
selected anchor remained stable. This is the desired separation: different valid
investigation paths may cite different supporting records without changing the
rubric-defined conclusion.

The result supports the local anchor correction but does not establish general
accuracy. There is still no human Gold, and only one case/question was tested.

## Cross-case generalization gate for v3

The `1/1/1` focused result is an in-sample result. It used the same attempt that
motivated the v3 wording, so v3 is currently classified as:

```text
locally validated rubric candidate
```

It is not yet classified as generalized, production-stable, or human-aligned.
To avoid continuing to tune on the smoke case, v3 is now frozen while a blind
review set is prepared from archived AgentOctagon traces.

The reusable offline scanner is:

```text
src/agenteval/meta_eval/failure_validation.py
tools_build_failure_handling_validation.py
```

It scans normalized structured runtime fields for candidates such as:

```text
non-zero exit
structured timeout
tool error/rejection
failed check output
exit-0 error text
non-fatal warning
shell fallback branch
observer/capture failure
```

Important boundary:

```text
automatic signal discovery != recovery judgment != Gold
```

The scanner never declares that a failure was ignored, partially recovered, or
fully recovered. A later successful event with compatible generic context is
recorded only as `later_success_candidate_refs`. Formal A-H strata,
applicability, required evidence, and the expected `0/0.5/1` anchor remain blank
for human review.

A first offline pass scanned 352 real attempts and produced 16 packets from 16
different environments under:

```text
run/meta_eval/failure-handling-blind-v1/
```

Both the development attempt and the entire
`agent-workspace-smoke-test` environment are excluded from selection. The run
contains no Judge API calls and no automatic Gold labels.

The first implementation initially over-selected failures because arbitrary
assistant/code text in `events.jsonl` could mention words such as `timeout` or
`error`. Real cross-environment inspection caught this. Detection was corrected
to require structured operation result/lifecycle fields; observer failures
require structured capture-event status/reason fields. A second observed case—a
successful command printing documentation containing the word `error`—is still
kept only as an `exit_zero_error_text_candidate`, demonstrating why heuristic
candidate discovery must not be promoted to Gold.

This infrastructure improves the validity of the upcoming test but does not yet
answer whether v3 generalizes. That requires human review of the packets followed
by repeated real Judge runs on approved unseen cases.

## Four-level resolution experiment (prepared, not yet run)

To test whether the three-level ladder itself is a source of error, an isolated
v4 variant has been added:

```text
experimental-2026-08-26.discrete-anchors-v4-four-level
```

It changes only the declared per-question score ladder:

```text
v3: 0 / 0.5 / 1
v4: 0 / 0.333333 / 0.666667 / 1
```

The question IDs, question text, evidence policy, capabilities, weights, and
Judge investigation behavior are unchanged. No new mandatory query or prompt
instruction has been added. The extra levels split the old partial region into
`limited` and `substantial`; this is an experimental factor, not a production
rubric change.

The comparison must use the same frozen trace, model, configuration, and repeat
count. It should report per dimension:

```text
selected anchor distribution
mean/std/range
exact anchor agreement
score variance
claim/evidence overlap
```

The result must not be interpreted as “more levels are better” merely because
scores look more precise. More levels may instead increase boundary ambiguity
and stochastic disagreement. A human Gold set is required before calling one
variant more accurate.

## First human Gold tranche

The first 16 unseen failure-handling packets were manually reviewed against the
frozen v3 definition. Gold records are stored at:

```text
run/meta_eval/failure-handling-blind-v1/gold/
```

The review found 7 applicable explicit-failure cases and 9 cases where this
specific dimension is not applicable (observer-side capture error, handled
fallback/warning, no explicit failure, or text-only false positive). Two cases
were scored `0` because a direct agent-visible failure remained unresolved; the
other 14 were scored `1` because the failure was successfully recovered or no
applicable failure was established. No `0.5` case occurred in this selected
tranche, so a separate partial-recovery sample is still required.
