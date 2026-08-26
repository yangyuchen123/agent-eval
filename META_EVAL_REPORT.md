# AgentEval Meta-Evaluation Report

**Status date:** August 26, 2026  
**Phase:** Judge Reliability / Meta-Evaluation  
**Verdict:** infrastructure and real stability experiments are operational, but
human-agreement and accuracy claims remain unavailable until the calibration
packets are reviewed into GoldJudgment records.

## 1. Current evidence base

### Real data inventory

AgentOctagon discovery currently exposes:

```text
84 environments
600 database attempt records
582 attempt directories
352 attempts with trace.jsonl
529 attempts with wire.jsonl
49 repeated env+task groups
307 attempts inside repeated groups
```

### Real Judge experiments

```text
77 external Judge calls completed
6 cases in the frozen generic-process repeated batch
2 cases in corrected order/trace-length perturbations
2 cases in the first three-mode comparison
30 balanced human Gold review packets prepared, but not yet reviewed
```

Saved run artifacts are under ignored local paths:

```text
run/meta_eval/
```

Each completed run saves manifest, judgments, failures, metrics and a Markdown
report. Query trajectory, evidence refs, model usage, latency, cost and frozen
snapshot digests are preserved.

## 2. First three-mode comparison

Protocol:

```text
2 real short-trace cases
× Agentic Evidence / Full-Trace / Static Retrieval
× 3 repeats
= 18 calls
```

| case | mode | scores | mean | std | status agreement | mean latency | mean cost |
|---|---|---|---:|---:|---|---:|---:|
| workspace smoke | Agentic | .32/.35/.18 | .2833 | .0907 | true | 39.1s | $0.005792 |
| workspace smoke | Full-Trace | .32/.35/.32 | .3300 | .0173 | true | 26.2s | $0.003434 |
| workspace smoke | Static | .45/.35/.40 | .4000 | .0500 | true | 24.1s | $0.001978 |
| edit repair | Agentic | .96/.98/.86 | .9333 | .0643 | true | 21.9s | $0.002461 |
| edit repair | Full-Trace | .88/.95/.93 | .9200 | .0361 | true | 16.3s | $0.001302 |
| edit repair | Static | .90/.92/.90 | .9067 | .0115 | true | 17.2s | $0.001353 |

Across the six observations per mode:

| mode | mean latency | mean input tokens | mean requests | mean tool calls | total cost |
|---|---:|---:|---:|---:|---:|
| Agentic | 30.5s | 15,767 | 3.33 | 4.17 | $0.024759 |
| Full-Trace | 21.2s | 13,846 | 1.00 | 0 | $0.014206 |
| Static | 20.7s | 5,545 | 1.00 | 0 | $0.009993 |

On these deliberately short traces, Agentic did not demonstrate a stability,
latency or cost advantage. This is not an accuracy ranking because no human Gold
exists and short traces are favorable to Full-Trace and Static Retrieval.

Detailed audit:

```text
docs/META_EVAL_THREE_MODE_RESULTS_2026-08-26.md
```

## 3. Important interpretation of the high-scoring edit case

`att_9ede41110391` contains three direct events:

```text
Read dashboard.py
one batch Edit containing all requested changes
post-edit Read dashboard.py
```

The task explicitly required a final Read to confirm the changes and did not
require executable tests. The final file content and checksum agree with the
Edit result. Thus the 0.86–0.98 scores are not automatically an evidence-
sufficiency failure; readback is a task-specified validation action here.

An indirect runtime capture record reports `parse_failed`. Some runs penalized
this as unhandled failure evidence. Gold review must decide whether observer-side
capture failures are applicable when they were not clearly visible to the agent
and do not contradict the direct file-edit events.

## 4. Reliability findings currently supported

1. Reliability is strongly case/question dependent.
2. A frozen generic question greatly reduced the extreme instability seen in the
   first bundled-question experiment, but did not eliminate score variation.
3. Evidence refs can remain identical while score and claim decomposition vary;
   this is reasoning/anchor variation rather than retrieval variation.
4. Top-level status was stable across all modes and repeats in the first two-case
   comparison.
5. Agentic runs on the two short cases used only broad search. No run used
   `get_evidence`, `get_call_context`, or `get_related_evidence`.
6. Search-only behavior is not automatically wrong when search returns complete
   records and the trace is short, but it means this batch does not test the
   principal value of agentic navigation.
7. Exact claim-ID agreement is low and must not be presented as semantic claim
   agreement.
8. The first baseline comparison contains a prompt-policy confound because the
   baseline and Agentic system instructions are similar but not text-identical.
9. Existing results support the presence of R12 stochastic instability in some
   groups; R1–R10 rates remain unavailable without Gold.
10. Current evidence does not justify claiming that Agentic is superior to either
    baseline.

## 5. Diagnostic infrastructure correction

The R12 classifier had two issues:

- it omitted the current judgment when checking repeated-run instability;
- floating-point representation could treat a nominal range of exactly 0.1 as
  greater than 0.1.

Both are fixed and regression-tested. No model score, status, claim or evidence
reference was modified. The corrected three-mode analysis identifies two Agentic
R12 groups with ranges 0.17 and 0.12.

## 6. Answers to the required report questions

### 1. Human Gold agreement

**Unavailable.** Thirty review packets exist, but none is yet an approved Gold.

### 2. Retrieval versus reasoning error share

**Unavailable as a population rate.** Individual audits already show both kinds
of risk. The smoke three-mode run specifically shows score variation despite
identical Agentic evidence refs, indicating post-retrieval reasoning/anchor
variation.

### 3. Repeated-run stability

Measured for real cases. It ranges from very stable (`std≈0.01`) to clearly
unstable (`range=0.17` in the current comparison and much larger in the first
exploratory bundled-question run).

### 4. Evidence order sensitivity

On two corrected cases, order shuffle changed mean score by `+0.0500` and
`-0.0200`. Evidence selection remained highly overlapping. More Gold cases are
required before estimating an error rate.

### 5. Distractor degradation

**Unavailable.** The primitive exists, but no reviewed semantic-distractor batch
has been run.

### 6. Evidence removal sensitivity

**Unavailable.** It requires human-approved required evidence refs so that the
experiment removes genuinely necessary evidence rather than guessed evidence.

### 7. Trace-length robustness

Corrected synthetic 2× no-op lengthening changed mean score by `+0.0033` and
`-0.0233`; no synthetic evidence was selected. This is promising but only covers
two cases and 2× length.

### 8. Agentic versus Full-Trace

On two short traces, Agentic was less score-stable, slower and more expensive.
Accuracy superiority is **unavailable** without Gold. Long and relational traces
have not yet been compared across all three modes.

### 9. Extra cost and latency

In the first three-mode batch, Agentic was approximately 1.44× slower and 1.74×
as costly as Full-Trace, and approximately 1.48× slower and 2.48× as costly as
Static Retrieval.

### 10. Three largest current credibility risks

1. no human-reviewed evidence-level Gold;
2. score/anchor variation after essentially identical evidence retrieval;
3. method-comparison confounds and insufficient long/relational cases.

## 7. Next experiment gate

Do not expand Judge or EvidenceCatalog features before completing a first reviewed
Gold tranche. The next controlled sample should deliberately contain:

```text
short direct trace
long noisy trace
multi-agent handoff/consumption trace
artifact-success versus runtime-failure conflict
human-approved key-evidence removal pair
```

Only after those cases are reviewed should the system run the next three-mode,
removal, distractor and paraphrase batches.

## 8. Scoring protocol change after the three-mode audit

The first three-mode experiment used the historical bundled question and is kept
unchanged as an audit artifact. Its identical-evidence/different-score behavior
motivated a new protocol rather than a post-hoc score correction.

The completed first fine-grained experiment used v2. Future experiments use:

```text
generic-runtime-process-reliability@frozen-2026-08-26.discrete-anchors-v3
```

with five independent dimensions:

```text
task_understanding
required_action_execution
result_validation
observed_failure_handling
completion_claim_integrity
```

Each dimension must select one concise `0 / 0.5 / 1` anchor. Continuous values
such as `0.86` are rejected for structured-anchor questions. This keeps evidence
investigation autonomous while moving score weighting and anchor definitions out
of ad-hoc Judge reasoning and into reviewable AgentEval rubric data.

## 9. First real discrete-anchor result

The first v2 fine-grained run used 15 real calls on the previously unstable smoke
case. Four of five dimensions had exact `0/0.5/1` anchor agreement. Failure
handling produced `0/0/1`, so the aggregate remained unstable at `0.3/0.3/0.5`.

This result shows that discrete anchors are not sufficient by themselves. They
make disagreement attributable, but each dimension must also be semantically
orthogonal. The v2 failure anchor mixed operation failures, wrong outcomes and
unsupported completion claims. The preserved v2 rubric has now been superseded
for new runs by `frozen-2026-08-26.discrete-anchors-v3`, which narrows failure
handling to explicit agent-visible operation or validation failure signals.

Detailed evidence audit:

```text
docs/META_EVAL_DISCRETE_ANCHOR_RESULTS_2026-08-26.md
```


## 10. v3 focused anchor validation

Three real repetitions of the corrected `observed_failure_handling` question
produced `1/1/1`, compared with v2's `0/0/1`. Evidence selection still varied
(pairwise Jaccard `0.7672`), but the anchor selection was invariant. The runs
consistently treated the missing-bashrc message as a successfully handled fallback
and terminal warnings as non-fatal, while leaving wrong outcomes and unsupported
claims to their independent dimensions.

This validates the local rubric-boundary correction on one case; it does not yet
prove human agreement or cross-case stability.

## 11. Discrete-anchor generalization status

The v3 failure-handling anchor removed the instability observed on its
rubric-development case, but that is not evidence of cross-case generalization.
The rubric is frozen as a locally validated candidate.

A reusable offline blind-set builder now scans 352 archived AgentOctagon attempts
and writes 16 human-review packets from 16 distinct environments. The original
attempt and its entire environment are excluded. No model calls or automatic
Gold judgments are involved.

The scan itself produced a useful reliability finding: unconstrained keyword
matching over nested event content creates false runtime failures when prompts,
code, or documentation merely mention `error`/`timeout`. The scanner now accepts
operation signals only from structured result/lifecycle fields and records all
D-H classifications as review candidates rather than facts.

Human-reviewed applicability, A-H stratum, required evidence, and expected
anchor are still unavailable. Consequently, the v3 patch's empirical
cross-environment accuracy remains **unavailable**, not assumed.

## 12. Human Gold availability

A first human-reviewed Gold tranche now exists for the unseen failure-handling
packets:

```text
run/meta_eval/failure-handling-blind-v1/gold-manifest.json
```

It now contains 17 question-level Gold judgments with direct evidence references,
applicability, A-H stratum, expected score, and missing-evidence notes. A first
partial-recovery case was added on 2026-08-26:

```text
att_f7830b42a3d8 → observed_failure_handling = 0.5
B_explicit_failure_partial_recovery
```

The current distribution is 2 zeros, 1 half-score, and 14 ones. This is enough to
show that the middle anchor can be represented by a real runtime case, but it is
still too dominated by score 1 to estimate partial-recovery accuracy or generalize
an anchor-count ranking. The next gate is to diversify Gold before running more
comparative Judge experiments: add at least 8 partial-recovery cases, 5 ignored
failure cases, 5 fully recovered cases, and 5 applicability-control cases. Gold
labels must remain human-maintained and must not be inferred from Octagon score.

Gold reference integrity can be checked with:

```bash
python3 tools_validate_failure_gold.py
```

The validator checks schema and evidence references only; it does not generate or
modify labels.

## 2-level anchor analysis (2026-08-26)

The completed 30-case, 3-repeat 2-level run is analyzed in:

```text
docs/META_EVAL_2_LEVEL_ANALYSIS_2026-08-26.md
```

It must not be interpreted as evidence that two-level scoring is more reliable merely because some cases repeat consistently. The run produced 51.11% strict Gold agreement (46/90), 52.87% agreement among available outputs (46/87), and MAE 0.3333. Its main limitation is structural: binary anchors cannot represent the eight human-reviewed partial-recovery Gold cases.
