# Retrieval-only Anchor Sensitivity（2026-08-27）

## 1. 研究问题

Frozen Evidence Scoring Ablation 表明，端到端的强 `resolution × wording` interaction 大部分不在最终 score mapping 阶段。下一步需要直接验证：

> rubric representation 是否改变 Autonomous Judge 的 retrieval policy？

本实验固定真实 runtime snapshot，只让 Agent 调查，不让它输出 score、status、confidence 或选择 anchor。

## 2. 设计

四个条件：

| Cell | Levels | Style |
|---|---:|---|
| A | 5 | qualitative |
| B | 5 | continuum |
| C | 6 | qualitative |
| D | 6 | continuum |

规模：

```text
5 cases × 4 conditions × 3 repeats = 60 observations
```

控制：

- 每个 case 的四格使用同一个 snapshot record digest；
- task、rubric question、evidence policy 均相同；
- 只有 score-anchor representation 改变；
- Agent 使用与 QuestionJudge 同名、同语义的通用工具：
  - `search_evidence`
  - `get_evidence`
  - `get_call_context`
  - `get_related_evidence`
- 没有 mandatory tool call；
- 没有 question-specific retrieval；
- 没有 final score 输出；
- production QuestionJudge instruction 没有为本实验调整。

为避免 EvidenceCatalog 内部导航调用污染工具计数，本实验额外记录 **agent-level tool trajectory**。因此 `get_related_evidence` 内部调用 provider `get()` 不会被误计为 Judge 主动调用 `get_evidence`。

## 3. Snapshot 规模

| Case | Runtime-neutral records |
|---|---:|
| `att_07d7cc78f5b0` | 23 |
| `att_8ca4f9ec3ba9` | 5,112 |
| `att_9c539666b31d` | 797 |
| `att_a1bb35bb6955` | 73 |
| `att_fa8655f8ce1d` | 363 |

长 trace case 被保留，没有为降低成本预先制作 question-specific packet。

## 4. Aggregate retrieval 结果

| Cell | Tool calls | Searches | Gets | Depth | Exposed IDs | Cited IDs | Required exposure recall | Required citation recall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A 5 qualitative | 5.00 | 3.07 | 1.87 | 1.53 | 15.53 | 5.73 | 1.000 | 1.000 |
| B 5 continuum | 5.40 | 2.60 | 2.73 | 1.80 | 14.47 | 4.87 | 1.000 | 1.000 |
| C 6 qualitative | 4.87 | 2.47 | 2.40 | 1.53 | 16.13 | 5.20 | 1.000 | 1.000 |
| D 6 continuum | 4.13 | 2.87 | 1.13 | 1.60 | 14.73 | 5.07 | 0.958 | 0.958 |

说明：observer/applicability case 没有 required refs，因此 required recall 汇总基于其余 12 个 observation。

唯一 required-evidence miss：

```text
att_8ca4f9ec3ba9
D_6_continuum
repeat=2
```

该轮找到了第二次 preview failure `trace.jsonl:15`，但没有展开第一次缺少 Playwright 的 failure `trace.jsonl:13`，所以 required recall 为 0.5。其余 47 个有 required refs 的 observation 都达到 1.0。

## 5. 关键比较：跨 representation 差异是否超过自身随机波动？

只看到 cross-condition Jaccard 不够，因为同一 condition 的三次重复本身也会走不同查询路径。因此本实验将跨条件 Jaccard 与左右两格的 pooled within-cell Jaccard 比较。

### Wording effect at 5 levels：A vs B

```text
Exposed evidence:
跨条件 Jaccard = 0.702
同格随机基线 = 0.735
差值 = -0.033

Cited evidence:
跨条件 Jaccard = 0.690
同格随机基线 = 0.696
差值 = -0.006
```

### Wording effect at 6 levels：C vs D

```text
Exposed evidence:
跨条件 Jaccard = 0.730
同格随机基线 = 0.696
差值 = +0.034

Cited evidence:
跨条件 Jaccard = 0.677
同格随机基线 = 0.652
差值 = +0.025
```

六挡下，跨 wording 的 evidence set 甚至比同一 wording 的重复运行更相似。这不支持“wording 稳定地改变 retrieval set”。

Resolution comparisons 也相同：cross-minus-within gap 只有约 `-0.020` 到 `+0.038`，没有出现远大于 stochastic baseline 的系统性分离。

## 6. Tool depth 与停止行为

不同 cell 的平均 tool calls 为 `4.13–5.40`，平均 depth 为 `1.53–1.80`。配对差异相对于 run-level 波动较小：

```text
A → B: tool calls +0.40, depth +0.27
C → D: tool calls -0.73, depth +0.07
A → C: tool calls -0.13, depth  0.00
B → D: tool calls -1.27, depth -0.20
```

只有 4/60 observation 使用了 `get_related_evidence`，没有一轮调用 `get_call_context`。但本问题是单 agent failure-handling，不要求证明跨 agent relation，因此不能仅凭 navigation depth 较低判定调查失败。

当前样本与三次重复不足以将这些小差异归因于 representation。更合理的结论是：

> representation 可能影响单轮 query wording 和停止点，但没有证据表明它在该五-case集合上形成了超过固有 stochastic variation 的稳定 retrieval policy shift。

## 7. 真正的主要失败：找到证据后的 applicability interpretation

Observer/capture control 的人工 audit：

```text
att_07d7cc78f5b0
Gold runtime fact:
parse_failed 是 observer/capture-layer event，未证明对被测 agent 可见。
```

12 轮 retrieval-only 结果：

```text
正确区分 observer-side event：4
错误当成 agent-visible failure：7
被 Judge 自身工具错误污染：1
```

分条件：

```text
A 5 qualitative: 0/3 correct
B 5 continuum:   1/3 correct，另 1 轮 self-tool contamination
C 6 qualitative: 2/3 correct
D 6 continuum:   1/3 correct
```

这不是 search failure。相关 `parse_failed`、成功 Edit/Read 和 capture metadata 都能被找到；失败发生在 evidence interpretation / source applicability。

因此 frozen scoring 实验中 applicability 被固定后四格都恢复为 1.0，并不是因为某个 ladder 更善于检索，而是因为冻结事实绕过了当前最不稳定的解释环节。

## 8. 新发现：Judge 自身 Evidence Tool error 污染被评估 runtime

`B_5_continuum repeat=0` 中，Investigator 尝试：

```text
search_evidence(limit=50)
```

底层 `EvidenceQuery` 只允许 `limit <= 30`。模型收到工具参数校验错误后，在最终 factual summary 中将它描述成：

```text
an explicit tool-validation failure occurred
```

也就是把 **Judge 自己调查环境中的工具错误** 当成了 **被测 agent 的 runtime failure**。

另一轮 `D_6_continuum repeat=1` 遇到同类错误，但正确明确区分其属于调查工具而非被测 runtime。这说明隔离能力本身也存在 stochastic instability。

这是一个正式 failure mode：

```text
judge-observation self-contamination
```

它不属于 EvidenceCatalog search recall，也不是被测 agent trace 的事实。

实验后做了通用 schema integrity 修复：`search_evidence.limit` 的公开 tool schema 现在明确声明 `1 <= limit <= 30`，与底层 EvidenceQuery 一致。没有添加 question-specific rule，也没有修改 Judge prompt。未来 run 还会保存完整 PydanticAI message history，以便审计工具参数校验失败；本轮原始数据不补造不存在的 message provenance。

## 9. Gold validity 问题

本实验还暴露出旧 numeric Gold 与新 anchor ladder 语义冲突。

### `att_fa8655f8ce1d`

旧 Gold：

```text
0.0
```

但五挡 qualitative 明确规定：

```text
0.25 = failure acknowledged or recovery attempted, but mostly unresolved
```

六挡 qualitative 明确规定：

```text
0.2 = failure acknowledged, no effective recovery
```

该 agent 明确承认 `g++` 缺失但没有恢复，所以对新 ladder 而言正确 expected anchor 应是 0.25/0.2。继续使用旧 Gold=0 会把“准确遵守新 rubric”统计成错误。

### `att_9c539666b31d`

旧 Gold=0.5 的理由要求证明所有更广泛的任务需求都被重新验证。但 `observed_failure_handling` 只问可见 failure 是否被处理。实际 trace 显示 IndentationError 和非有限指标都经过修改，最终 compile/structural/finiteness validation 成功。

因此这一 case 对 failure-handling 应更接近 1.0；缺失完整 task-contract 验证属于 `result_validation`。旧 Gold 在这里跨越了 rubric boundary。

为避免 post-hoc 静默改标签，新增：

```text
meta_eval/gold_adjudication_failure_handling_v2/
```

它不覆盖原 Gold，而是记录 representation-neutral factual state 和四个 ladder 的 expected anchor。

## 10. Anchor-aware 离线重分析

### End-to-end

| Cell | 原 MAE | Anchor-aware MAE | Anchor-aware Exact |
|---|---:|---:|---:|
| A | 0.183 | **0.033** | **0.867** |
| B | 0.417 | 0.267 | 0.600 |
| C | 0.373 | 0.213 | 0.667 |
| D | 0.333 | 0.173 | 0.733 |

MAE interaction 仍是：

```text
-0.2733
```

因为 anchor-aware Gold 对同一 resolution 下的 qualitative/continuum 使用相同 expected numeric anchor，所以 wording crossover 的 MAE interaction 没有消失。此前“强端到端 interaction”的主结论仍成立。

但绝对准确率、case failure 归因和“negative control”解释发生了显著变化。

### Frozen scoring

| Cell | 原 MAE | Anchor-aware MAE | Anchor-aware Exact |
|---|---:|---:|---:|
| A | 0.167 | 0.083 | 0.667 |
| B | 0.133 | **0.017** | **0.933** |
| C | 0.120 | 0.040 | 0.800 |
| D | 0.133 | 0.027 | 0.867 |

Frozen MAE interaction：

```text
+0.0533
```

仍远小于端到端的 `-0.2733`。所以“强 interaction 主要发生在 investigation/interpretation loop”的结论保持不变。

需要撤回的是：

> `att_9c539666b31d` 是 rubric-representation-insensitive scoring failure。

Anchor-aware adjudication 下，它多数输出实际上符合 failure-handling anchor；原先所谓稳定高估很大程度来自 Gold/rubric boundary 错位。

## 11. 成本

```text
60 observations
provider cost: 0.45290736
input tokens: 2,974,926
output tokens: 66,997
mean latency: 28.29 s/observation
```

成本明显高于 frozen scoring，主要因为通用搜索返回完整高信息密度 records，且其中一个 snapshot 有 5,112 records。当前不据此削薄 Evidence Tool；该问题应在独立 token/cost 实验中处理。

## 12. 最终结论

本轮没有得到“anchor wording 明显改变 retrieval policy”的强证据。

更准确的分解是：

```text
Required evidence retrieval:
基本稳定，四格只有一轮部分漏检

Retrieved/cited evidence set:
有变化，但变化规模与同条件重复运行的随机变化相当

Evidence interpretation / applicability:
明显不稳定，是当前主要 failure

Score mapping:
存在较小 interaction，但远小于端到端 interaction

Gold measurement:
旧 numeric Gold 与新 anchor semantics 存在冲突，需要 anchor-aware Gold
```

因此不应马上扩大 retrieval-only case 数。下一步先完成：

1. 将 Gold 数据模型从单一 numeric score 扩展为 factual state + rubric-bound expected anchor；
2. 增加 `judge_self_observation_contamination` failure taxonomy；
3. 用已有 30-case Gold 审查 rubric-boundary leakage；
4. 再按 endpoint failure、partial recovery、observer/applicability、semantic reasoning failure、easy success 分层扩展。

## 13. 产物

```text
judge/src/agentjudge/investigation.py
judge/tests/test_retrieval_investigation.py
tools_run_retrieval_only_anchor_sensitivity.py
tools_analyze_retrieval_only_anchor_sensitivity.py
tools_reanalyze_anchor_ablation_with_adjudicated_gold.py
meta_eval/gold_adjudication_failure_handling_v2/
run/meta_eval/retrieval-only-anchor-sensitivity-v1/
run/meta_eval/anchor-aware-gold-reanalysis-v1/analysis.json
```

## 14. 本轮随后完成的基础设施修正

报告第 12 节列出的前两项已在本轮实现：

1. `GoldJudgment` 新增可选字段：

   ```text
   factual_state
   expected_score_by_policy
   rubric_boundary_notes
   ```

   `score_for(policy_id)` 会优先解析 policy/rubric-specific expected score，同时保留旧 `expected_score`，因此不会破坏历史 Gold replay。

2. Failure taxonomy 新增：

   ```text
   R13 judge_environment_contamination
   ```

   自动分类只接受显式 provenance 标记，不根据文本关键词猜测，避免把诊断规则变成新的脆弱 grader。

30-case rubric-boundary Gold audit 尚未执行；在完成该审查前，不应继续扩大 anchor-count 结论。
