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

## Controlled 2-vs-5 level comparison (2026-08-27)

The completed controlled experiment is documented in:

```text
docs/META_EVAL_2_VS_5_LEVEL_RESULTS_2026-08-27.md
```

Both conditions used 30 human-reviewed Gold cases and three repeats. Strict exact Gold accuracy was identical at 51.11%, while MAE improved from 0.3333 with two anchors to 0.2079 with five anchors. Five anchors reduced quantization error but increased cost by approximately 68% and reduced exact-score-stable cases from 24/30 to 20/30.


## Five-case 2-to-9-level anchor experiment (2026-08-27)

The controlled small-case experiment is documented in:

```text
docs/META_EVAL_ANCHOR_SMALL_TURNING_POINT_2026-08-27.md
```

It now covers five deliberately diverse Gold cases, eight anchor-count conditions, and three repeats per condition (120 real observations). Conditions 6–9 added 60 observations with recorded provider cost `0.6994008`. All levels used the same model, seeds, case traces, and trace digests. Five levels formed a multi-metric local optimum between four and six levels: MAE `0.311 → 0.183 → 0.333`, RMSE `0.451 → 0.266 → 0.507`, and threshold agreement `0.667 → 0.933 → 0.600`. However, levels 6–9 were strongly non-monotonic rather than a smooth bell curve. The result is exploratory, sensitive to individual difficult cases, and partially confounded by the generic continuum wording used for newly generated 6–9-level intermediate anchors. A nine-level observation also exposed a 922k-input-token tail-cost event caused by an over-broad related-evidence traversal.

## Anchor count × wording 2×2 ablation (2026-08-27)

The decisive follow-up is documented in:

```text
docs/META_EVAL_ANCHOR_WORDING_2X2_ABLATION_2026-08-27.md
```

The missing 5-level continuum and 6-level qualitative cells added 30 real observations at recorded provider cost `0.20262488`. The result is a strong crossover interaction rather than an independent anchor-count effect. Under qualitative wording, moving from five to six levels worsened MAE by `+0.190`; under continuum wording it improved MAE by `-0.083`. At five levels, continuum wording worsened MAE by `+0.233`; at six levels it improved MAE slightly by `-0.040`. The interaction magnitude (`0.273` in MAE difference-in-differences) exceeds both average main effects. Consequently, the previously observed five-level optimum must be interpreted as an advantage of the specific `5-level qualitative` combination, not a wording-independent resolution optimum. Case audit also shows that wording changed evidence applicability interpretation and investigation trajectories, including observer-side capture failures being mistaken for agent-visible failures.

## Frozen-evidence scoring-only ablation（2026-08-27）

详细报告：

```text
docs/META_EVAL_FROZEN_EVIDENCE_SCORING_ABLATION_2026-08-27.md
```

在 5 个真实 case 上冻结人工审阅的 evidence facts、claim set、missing facts 与 source applicability 后，四种 `5/6 levels × qualitative/continuum` 表达的 MAE interaction 从端到端 Agentic Judge 的 `-0.2733` 缩小到 `+0.0467`，绝对 interaction retention ratio 为 `0.1707`；Exact interaction 的绝对保留比例为 `0.25`，且方向同样反转。Observer/capture control 在冻结 applicability 后四格全部恢复为 1.0，ignored-failure case 也不再因漏检关键编译失败而得到 1.0。

当前结论是：此前强 crossover interaction 主要来自 rubric representation 对 retrieval / interpretation / applicability / stopping loop 的影响，而不是纯 score-anchor mapping。Scoring representation 仍有较小、case-local 的作用；negative-control partial-recovery case 在冻结事实后仍被系统性高估，说明还存在 scoring interpretation / anchor-alignment failure。下一步应进入 retrieval-only sensitivity，而不是继续增加挡位或调整 prompt。

## Retrieval-only anchor sensitivity（2026-08-27）

详细报告：

```text
docs/META_EVAL_RETRIEVAL_ONLY_ANCHOR_SENSITIVITY_2026-08-27.md
```

在固定 5 个真实 runtime snapshot、移除最终评分后完成了 60 次调查。四格 required evidence exposure/citation recall 分别为 `1.000 / 1.000 / 1.000 / 0.958`，只有一轮部分漏检。五挡 A/B 的跨 wording exposed-evidence Jaccard 为 `0.702`，而 pooled within-cell stochastic baseline 为 `0.735`；六挡 C/D 分别为 `0.730` 与 `0.696`。跨 representation 的 evidence-set 差异没有明显超过同条件重复运行自身的随机变化，因此当前没有强证据说明 anchor wording 形成稳定 retrieval-policy shift。

真正突出的失败是 evidence applicability interpretation：observer/capture control 的 12 轮中只有 4 轮正确区分 observer-side `parse_failed`，7 轮误当成 agent-visible failure，另 1 轮被 Judge 自身 Evidence Tool 参数错误污染。该工具 schema mismatch 已通过给 `search_evidence.limit` 声明 `1..30` 约束修复，未增加 question-specific policy 或修改 Judge prompt。

实验同时发现旧 numeric Gold 与新 anchor semantics 冲突。已新增 post-hoc、非覆盖式 anchor-aware Gold adjudication。重分析后，端到端 MAE interaction 仍为 `-0.2733`，frozen-scoring interaction 为 `+0.0533`，所以“强 interaction 主要发生在 investigation/interpretation loop”的结论保持；但 `att_9c539666b31d` 原先所谓 negative-control scoring failure 应撤回，它主要是 Gold 与 rubric boundary 错位。

本轮随后已扩展 `GoldJudgment`，支持 `factual_state + expected_score_by_policy + rubric_boundary_notes`，并新增显式诊断类别 `R13 judge_environment_contamination`。二者都向后兼容：旧 numeric Gold 保留，R13 仅在 provenance 明确标记时自动归类，不使用文本启发式猜测。
