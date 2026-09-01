# AgentEval 三类测量误差分解实验协议

日期：2026-08-31  
状态：冻结协议，尚未运行新 Judge/Harbor/Pi。

## 1. 目的

在不重新运行 Harbor/Pi 的前提下，使用冻结的 Gold、response、trajectory 和 Judge 输入，分离：

```text
rubric representation error
 evidence access error
semantic inference error
```

本协议不评价 Gold 标注质量，也不把单次 disagreement 自动解释为 benchmark 难度或 Judge 缺陷。

## 2. 固定项

每个实验 case 必须固定：

- benchmark/case ID；
- response 或历史 trajectory；
- Gold label/score/status；
- Judge model、provider、sampling 参数；
- AgentEval/Judge 服务版本；
- case adapter 版本；
- evidence record 的原始 digest；
- 评估输出的 binary mapping 规则。

## 3. 三个因素

| 因素 | 0 条件 | 1 条件 | 说明 |
|---|---|---|---|
| R：rubric representation | `R0_original` | `R1_decomposed` | 只改变 rubric/question 结构，不改变事实和 evidence |
| E：evidence access | `E0_current` | `E1_oracle_structured` | 只改变 Judge 可见证据，不改变 response/Gold/rubric |
| I：semantic inference | `I0_current` | `I1_controlled_anchor` | 只改变 anchor/inference wording；不改变 R/E |

第一轮若 `I1` 还不能由现有 prompt builder 稳定构造，则先执行 `R×E` 的 2×2，不强行声称完成 2×2×2。

## 4. 实验矩阵

### 4.1 第一阶段：R×E

```text
R0E0  原始 rubric + 当前 evidence
R0E1  原始 rubric + oracle/structured evidence
R1E0  decomposed rubric + 当前 evidence
R1E1  decomposed rubric + oracle/structured evidence
```

每个 cell 使用相同 fixture 和相同 Judge 配置。只在需要新 Judge judgment 的 cell 调用 AgentEval；不调用 Harbor/Pi。

### 4.2 第二阶段：加入 I

```text
R0E0I0  baseline
R0E0I1  只换 controlled anchor/inference
...
R1E1I1  full controlled condition
```

`I1` 的实现必须通过 manifest 显式记录 `anchor_prompt_digest` 和 `anchor_levels`，不能仅记录一个模糊的 “v2”。

## 5. 归因规则

- `E1` 恢复正确，且 R 不变：优先标为 evidence access/selection error；
- `R1` 恢复正确，且 E 不变：优先标为 rubric representation error；
- `R1E1` 仍错误：进入 semantic inference badcase 候选；
- 多个条件都正确或都错误：不强行归因；
- R、E、I 同时变化而无 cell 对照：该 case 不用于因果归因。

对每个 case 保存：

```json
{
  "case_id": "...",
  "gold": {"score": 1.0, "binary": true},
  "cells": {
    "R0E0": {"score": null, "binary": null, "status": "pending"},
    "R0E1": {"score": null, "binary": null, "status": "pending"},
    "R1E0": {"score": null, "binary": null, "status": "pending"},
    "R1E1": {"score": null, "binary": null, "status": "pending"}
  },
  "attribution": "pending",
  "evidence_refs": [],
  "provenance": {}
}
```

## 6. 现有数据可用性审计

### 6.1 60 条跨 benchmark Gold

现有路径：

```text
run/meta_eval/cross-benchmark-anchor-2-20260831/
run/meta_eval/cross-benchmark-anchor-5-20260831/
```

优点：有 60 条固定 Gold、response、rubric category 和 2/5 anchor 结果。  
限制：当前 `results.jsonl` 主要保存扁平化 judgment，单条结果没有完整 `provenance`，且多数 case 没有可 replay 的 runtime evidence。

因此这批数据适合：

- anchor wording/levels 的离线 paired 分析；
- rubric taxonomy 分层；
- raw score/threshold 分析。

暂不适合直接作为完整 E0/E1 runtime oracle 实验集。

### 6.2 AgenticCoding / Octagon trajectory

现有路径：

```text
run/meta_eval/ruverbench-agenticcoding-agent-eval-pilot-v1/
run/meta_eval/octagon-real/
run/launch-readiness-preference-study/
```

这些 case 更适合作为第一批 E0/E1 候选，因为存在 trajectory 或 EvidenceRecord 来源。但冻结前必须逐条确认：

- response 与 trajectory 的对应关系；
- artifact/trace digest；
- required evidence refs；
- Gold 来源与 status；
- serialized 与 structured condition 是否来自同一原始 run。

### 6.3 当前不能直接声称的内容

当前没有证据支持：

- 所有 60 条都可以做 oracle evidence；
- 2/5 差异完全来自档位数量；
- 某个单次低分就是 semantic inference failure；
- serialized trajectory 与 structured EvidenceRecord 已经在相同输入上完成 paired 实验。

## 7. 第一批实施边界

第一批只选择 3–5 个 evidence 充分的历史 case，优先：

1. 一个已知 evidence selection/retrieval 风险 case；
2. 一个 mixed artifact + runtime evidence case；
3. 一个 runtime-required case；
4. 若存在，再加入一个 rubric decomposition 已有对照的 case。

不重新生成 benchmark，不重新运行 Harbor/Pi，不修改生产 rubric 或 Judge service。

## 8. 成功标准

实验完成后必须能够逐条回答：

```text
该 case 在原始 rubric + 当前 evidence 下是否错误？
如果提供 oracle/structured evidence，是否恢复？
如果只分解 rubric，是否恢复？
如果两者都充分仍错误，是否可以归因到 semantic inference？
```

每个结论都必须绑定 fixture digest、condition manifest 和 result digest。

## 9. 本轮离线审计结果

本轮已对现有历史产物做候选盘点，并写入：

```text
run/meta_eval/factorial-error-decomposition-v1/fixture-readiness.json
```

当前结论是：

- 60 条跨 benchmark Gold 可以继续用于 anchor、threshold 和 rubric taxonomy 分析；
- 它们目前不能直接承担 runtime oracle evidence 因子，因为单条结果缺少完整 provenance binding；
- Octagon historical meta-eval 是第一批 `E0/E1` 候选；
- `att_07d7cc78f5b0`、`att_506b96de9919`、`att_35f7ed7f3d24` 已列为候选，但尚未 sealed；
- 不能把已有 2-level/5-level 结果直接当作新的 R×E 结果；
- 目前没有伪造 `oracle` 或 `decomposed` 结果。

因此下一步是 provenance binding，而不是运行实验：

```text
candidate case
→ 原始 trace/artifact 定位
→ Gold/rubric/question 绑定
→ EvidenceRecord ref 校验
→ input digest
→ sealed fixture
→ 才允许 AgentEval replay
```

## 10. Fixture sealing audit

已对三个候选 case 执行只读完整性检查，结果写入：

```text
run/meta_eval/factorial-error-decomposition-v1/fixture-sealing-audit.json
```

三者均通过：

- snapshot、packet、Gold 文件存在；
- snapshot 的 `trace_digest` 与 packet 一致；
- `record_count` 与实际 records 数量一致；
- Gold 中的 evidence refs 可以解析到 snapshot；
- historical judgment 存在且有 score；
- rubric/question 可从 packet 绑定。

因此三个 case **可以作为 evidence-level AgentEval replay 候选**。

但三者均不能标记为完整 run fixture `sealed`，因为当前 manifest 还没有绑定：

```text
original_trace_file
artifact
trial_result
native_session
atif_trace_file
verifier_result
```

所以当前采取两级状态：

```text
evidence_replay_sealable = true
full_run_fixture_sealable = false
```

这避免把一个可以做 Judge/evidence replay 的快照，错误宣称为包含完整 Harbor/Pi provenance 的 canonical run fixture。

## 11. R1 rubric decomposition view

已创建分析用 R1 view：

```text
run/meta_eval/factorial-error-decomposition-v1/rubric-variants/rubric-decomposition-view.json
```

R1 不改变 Gold，也不替换生产 rubric，而是把当前单问题拆成三个诊断面：

```text
failure_signal_observability
failure_response
 evidence_boundary
```

这样可以观察 Judge 的错误发生在：

- 是否识别出 agent-visible failure；
- 是否判断 recovery/response；
- 是否把 observer-side/documentation evidence 错当成 task failure。

R1 的聚合公式目前只作为分析候选：

```text
min(observability, response, evidence_boundary)
```

它不会覆盖 R0 的 score，也不会修改 Gold。R1 与 R0 之间必须在相同 evidence snapshot、相同 model/config 下 replay，才能解释为 rubric decomposition effect。

## 12. 当前实验 gate

manifest 已选择三个 `evidence_replay_sealable` 候选，但下一步仍需先人工审阅 R0/R1 语义等价性，然后才运行最小 baseline：

```text
R0E0 only
```

确认 baseline replay 与 historical judgment 一致后，才运行：

```text
R0E1 / R1E0 / R1E1
```

这一步避免把 fixture 装载差异、rubric 改写差异和 evidence 差异混为一个结果。
