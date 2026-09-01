# AgentEval Judge 跨 Benchmark 60 条 Pilot Badcase 分析

日期：2026-08-31  
状态：离线分析报告，不修改 AgentEval Judge、Rubric、Benchmark 或 Harbor/Pi。

## 1. 分析范围

本报告分析已经完成的三组 Judge pilot：

| Benchmark | 输入结果 | 样本数 | 样本单位 |
|---|---|---:|---|
| HealthBench | `run/meta_eval/healthbench-gold-v1/agent-eval-gold/` | 20 | prompt + completion + 一个 rubric |
| RuVerBench DeepResearch | `run/meta_eval/ruverbench-agent-eval-pilot-v1/` | 20 | research response + 一个 rubric point |
| RuVerBench AgenticCoding | `run/meta_eval/ruverbench-agenticcoding-agent-eval-pilot-v1/` | 20 | coding trajectory + 一个 checklist item |

本次定义：

```text
badcase = AgentEval prediction_binary != benchmark Gold binary
```

其中三个 pilot 都使用：

```text
prediction_binary = (AgentEval score >= 0.5)
```

本报告只做 badcase 定位和归因假设，不把自动分析假设当作新的 Gold，也不把每个 mismatch 直接认定为 Judge 模型错误。

机器可读的逐条分析位于：

```text
run/meta_eval/badcase-analysis-20260831/badcases.json
```

---

## 2. 总体结果

| Benchmark | 测试数 | Badcase | 正确数 | 错误率 |
|---|---:|---:|---:|---:|
| HealthBench | 20 | 7 | 13 | 35.0% |
| RuVer DeepResearch | 20 | 3 | 17 | 15.0% |
| RuVer AgenticCoding | 20 | 5 | 15 | 25.0% |
| **合计** | **60** | **15** | **45** | **25.0%** |

这 15 条 badcase 说明：

```text
Judge 调用成功率高
≠
Judge 判断质量已经可靠
```

之前三组运行均为：

```text
60/60 scored
0/60 execution errors
```

但仍有：

```text
15/60 binary mismatch
```

因此需要将以下两种质量分开记录：

1. **Execution reliability**：是否成功调用、解析和返回结果；
2. **Judgment correctness**：是否与外部 Gold 一致。

---

## 3. 错误方向

| Benchmark | False Positive | False Negative |
|---|---:|---:|
| HealthBench | 2 | 5 |
| RuVer DeepResearch | 1 | 2 |
| RuVer AgenticCoding | 1 | 4 |
| **合计** | **4** | **11** |

### 3.1 False Positive

```text
Gold = false
Judge = true
```

含义是 Judge 认为 rubric 已满足，但参考标签认为没有满足。

常见风险包括：

- 把提到相关内容当作真正满足 criterion；
- 只看到局部正确，忽略关键缺失或安全问题；
- 对 checklist 缺失行为判断过于宽松；
- 没有正确识别事实错误；
- 没有区分“部分满足”和“完全满足”。

### 3.2 False Negative

```text
Gold = true
Judge = false
```

含义是 Gold 认为 rubric 已满足，但 Judge 判定不满足。

常见风险包括：

- Judge 过度严格；
- 将局部瑕疵升级为整体失败；
- 没有识别隐含满足或等价表达；
- 把完整回答的质量要求误读成 criterion 必须无缺陷；
- trajectory 中存在行为，但没有从长文本中稳定识别出来。

本次 false negative 明显多于 false positive：

```text
11 vs 4
```

这初步显示当前 Judge 有偏严格倾向，但因为总样本只有 60 条，不能直接得出全局 bias 结论。

---

## 4. 按 Judge status 分布

15 条 badcase 的最终 Judge status：

| Status | 数量 |
|---|---:|
| `supported` | 8 |
| `contradictory` | 4 |
| `partially_supported` | 2 |
| `unverified` | 1 |

### 4.1 `supported` badcase

这类 badcase 特别重要，因为 Judge 自己认为结论有充分支持，但最终与 Gold 不一致。

它可能表示：

- Judge 的 rubric interpretation 错误；
- Judge 找到的“支持”与 Gold 所要求的支持不是同一件事；
- Judge 过度依赖表面匹配；
- checklist / coverage 语义被理解错；
- Gold 与当前适配后的 rubric 语义存在偏差。

### 4.2 `contradictory` badcase

部分样本中，claims 里同时出现：

```text
满足某个方面
```

和：

```text
存在关键问题或证据不足
```

最终 status 为 `contradictory`，但 score 可能直接为 `0.0`。

需要重点检查：

```text
claims
→ status
→ score
```

三者是否保持一致。

### 4.3 Claims 与最终 score 不一致

某些 coding badcase 中，Judge claims 明确描述 trajectory 包含要求的行为，但最终 score 仍然是 `0.0`。

这说明问题可能不只是外部 Gold mismatch，还可能存在：

```text
中间 claim 判断
→ 最终 QuestionJudgment score
```

之间的决策不一致。

这种情况应单独归类为：

```text
internal judgment consistency issue
```

而不能只归结为模型“不懂题”。

---

## 5. HealthBench Badcase 分析

HealthBench 结果：

```text
7/20 badcase
5 false negative
2 false positive
```

### 5.1 主要问题：整体质量判断压过单 criterion 判断

HealthBench physician label 对某条 rubric 的判断，可能允许：

```text
总体满足，但回答存在局部瑕疵
```

而当前 Judge 可能采用：

```text
只要发现重要缺陷
→ criterion 整体判为不满足
```

于是会出现：

```text
response 大部分满足
+ 局部医学表达不严谨
→ Judge score = 0
→ Gold = true
```

这类错误本质上可能是：

```text
binary criterion interpretation drift
```

而不一定是医学知识本身错误。

### 5.2 对医学回答局部缺陷过度惩罚

HealthBench badcase 的 claims 中，经常同时包含：

- 正确识别用户情况；
- 提供了合理建议；
- 发现部分措辞或安全限制不够严谨；
- 指出信息缺失或引用不充分。

但最终 score 仍为 `0.0`。

需要人工判断：

```text
该 rubric 是要求“完全无明显医学问题”
```

还是：

```text
该 rubric 只要求某个具体行为/内容出现
```

如果是后者，Judge 可能过度应用了整体医学质量标准。

### 5.3 高置信 false positive

HealthBench 中也出现：

```text
score ≈ 0.9
Gold = false
```

这说明 Judge 不仅存在轻微边界漂移，也可能在某些 context-seeking 或 emergency-related criterion 上高置信接受不符合要求的回答。

需要重点检查：

- 是否把一般建议误认为已完成 context seeking；
- 是否把提到潜在风险误认为已经给出充分安全指引；
- 是否忽略了 response 中的关键禁忌或错误；
- 是否将“部分安全”当成“满足完整安全标准”。

### 5.4 HealthBench 的 evidence 边界

当前 HealthBench replay 使用空 EvidenceCatalog：

```python
EvidenceCatalog([])
```

Judge 主要基于：

```text
prompt + completion + rubric
```

完成判断。

对于 response-only HealthBench，这种输入方式基本符合任务形态；但它无法进一步区分：

```text
医学语义推理错误
```

和：

```text
外部 evidence retrieval 错误
```

---

## 6. RuVerBench DeepResearch Badcase 分析

DeepResearch 结果：

```text
3/20 badcase
2 false negative
1 false positive
```

### 6.1 `facts` 类风险最明显

之前的类别指标为：

| 类别 | 数量 | Accuracy |
|---|---:|---:|
| `numbers` | 5 | 100% |
| `logic` | 5 | 100% |
| `format` | 5 | 80% |
| `facts` | 5 | 60% |

当前 badcase 也主要暴露出事实型 rubric 的边界问题。

Judge 可能没有稳定区分：

```text
response 提到了相关事实
```

与：

```text
response 对该事实做出了准确、充分且符合 rubric 的陈述
```

### 6.2 完整报告与单 rubric point 的粒度差异

DeepResearch 的输入是完整 research report，但 Judge 只判断其中一个 rubric point：

```text
完整 response
+ 一个 point
→ 一个 QuestionJudgment
```

完整报告中存在相关信息，并不代表当前 point 被明确、准确地满足。

反过来，某个 point 可能已经满足，但满足内容分散在报告多个段落，Judge 可能没有稳定整合。

因此 badcase 可能来自：

- Judge 只检查局部文本；
- Judge 被报告中其他相关内容干扰；
- Judge 将事实准确性要求高于 RuVerBench 的 coverage label；
- Judge 将 coverage label 误读成独立事实核验任务。

### 6.3 RuVerBench Gold 的语义边界

RuVerBench 的 label：

```text
covered = true / false
```

主要表示 rubric point 是否被覆盖。

它不一定完全等价于：

```text
response 中的事实是否经过独立外部核验
```

所以 DeepResearch badcase 需要人工区分：

1. 真正的 coverage error；
2. Judge 比 RuVerBench 更严格地检查 factual correctness；
3. RuVerBench reference 只关注提及，而 Judge 关注完整论证；
4. rubric point 本身存在边界模糊。

---

## 7. RuVerBench AgenticCoding Badcase 分析

AgenticCoding 结果：

```text
5/20 badcase
4 false negative
1 false positive
```

### 7.1 规则/工具 checklist 是主要风险

本次 badcase 涉及的典型 check 包括：

- 是否提供测试运行命令；
- 是否使用 `Task(subagent_type=Explore)`；
- 是否使用 `TodoWrite`；
- 是否调用特定 `Skill`；
- 是否满足 Explore、ToolSchema 或 system rule 要求。

这些 check 共同要求 Judge 从 trajectory 中精确识别：

```text
工具名称
工具参数
调用时机
调用结果
是否实际执行
```

它们不是普通自然语言回答判断。

### 7.2 当前 trajectory 仍是长文本输入

当前适配方式是：

```text
trajectory.messages
→ 序列化
→ JudgeRequest.agent_output
```

而不是：

```text
trajectory
→ EvidenceRecord[]
→ EvidenceProvider query
→ Judge
```

因此 Judge 可能无法稳定区分：

- 读取了 Skill 文件；
- 实际调用了 Skill 工具；
- 提到 Explore；
- 真的调用了 `Task(subagent_type=Explore)`；
- 执行过测试命令；
- 只是建议执行测试命令。

### 7.3 Claims 与 Gold 方向相反

某些 coding badcase 中，Judge claims 说 trajectory 包含要求的行为，但最终 prediction 仍为 false。

这至少暴露出一个待检查问题：

```text
claim extraction / interpretation
```

与：

```text
final score decision
```

之间可能不一致。

### 7.4 不能把当前 75% 解释成结构化 runtime evidence accuracy

当前结果更准确的表述是：

> AgentEval Judge 对 serialized coding trajectory 文本的 checklist 判断准确率为 75%。

不能直接表述为：

> AgentEval 已验证了 Judge 对 coding runtime evidence 的检索和判断能力。

---

## 8. 置信度分析

15 条 badcase 中：

```text
14 条 confidence >= 0.9
```

因此当前 `confidence` 不能直接当作正确率概率。

当前可能出现：

```text
confidence = 0.98
prediction = wrong
```

所以不应使用简单规则：

```text
低置信度 → 人工复核
高置信度 → 自动接受
```

需要单独做 confidence calibration：

```text
confidence bucket
→ empirical accuracy
```

建议至少输出：

| Confidence bucket | 实际 accuracy |
|---|---:|
| `0.0–0.5` | 待测 |
| `0.5–0.8` | 待测 |
| `0.8–0.9` | 待测 |
| `0.9–1.0` | 待测 |

当前 60 条样本中，14/15 badcase 属于高置信错误，已经足以说明 confidence 不能作为自动放行信号。

---

## 9. 跨 Benchmark 的共同问题

### 9.1 连续 score 与二元 Gold 的适配

当前请求使用的是类似：

```text
0 = not satisfied
1 = satisfied
```

但实际 Judge 仍然输出过：

```text
0.15
0.35
0.55
0.85
0.90
0.92
```

最后再用：

```text
score >= 0.5
```

转换成二元标签。

这意味着当前测试实际是：

```text
continuous Judge score
→ thresholded binary evaluation
```

而不是严格的：

```text
binary QuestionJudge
```

如果要测试二元 rubric，应使用结构化 `score_anchors`：

```json
{
  "score_anchors": [
    {
      "score": 0.0,
      "label": "not_satisfied",
      "description": "The criterion is not satisfied."
    },
    {
      "score": 1.0,
      "label": "satisfied",
      "description": "The criterion is satisfied."
    }
  ]
}
```

这样才能区分：

- Judge 的二元判断错误；
- Judge 的连续校准错误；
- threshold 造成的边界错误。

### 9.2 EvidenceRefs 为空

当前三组 pilot 的 `evidence_refs` 基本为空。

因此无法将 badcase 继续细分为：

```text
没有找到证据
```

还是：

```text
找到错误证据
```

还是：

```text
证据正确，但最终推理错误
```

这是后续 evidence-aware meta-eval 的关键缺口。

### 9.3 三个 Gold 语义不同

| Benchmark | Gold 含义 |
|---|---|
| HealthBench | physician 对 health completion/rubric 的判断 |
| DeepResearch | response 是否覆盖 rubric point |
| AgenticCoding | trajectory 是否满足 checklist check |

它们都被转换成 `true/false`，但 `true` 的实际含义不相同。

所以 15 条 mismatch 不能直接合并成一个“Judge 错误集合”而不保留 benchmark 语义。

---

## 10. 逐条 badcase 索引

完整逐条信息保存在：

```text
run/meta_eval/badcase-analysis-20260831/badcases.json
```

每条记录至少包含：

```text
benchmark
case_id
category
Gold
prediction
prediction score
confidence
status
rubric/check/point
Judge claims
evidence_refs
错误方向
临时错误类型
```

### 10.1 数量索引

```text
HealthBench: 7
RuVer DeepResearch: 3
RuVer AgenticCoding: 5
Total: 15
```

### 10.2 错误类型索引

当前机器可读记录中的 provisional type 是定位假设：

| Benchmark | Provisional type |
|---|---|
| HealthBench | `over_strict_or_safety_completeness` / `over_acceptance_or_context_misread` |
| DeepResearch | `coverage_semantics_or_fact_verification_error` |
| AgenticCoding | `trajectory_evidence_or_check_scope_error` |

这些类型不是新增 taxonomy，也不是自动替换原始 diagnosis。

---

## 11. Badcase 归因的判定边界

当前仅凭 pilot 输出，不能直接确定根因。每个 badcase 应经过人工复核，至少回答：

```text
1. Gold label 是否与原始 benchmark 语义一致？
2. rubric/check 是否单义？
3. response/trajectory 是否真的满足 criterion？
4. Judge claims 是否正确？
5. claims 与最终 score 是否一致？
6. status 与 score 是否一致？
7. 是否因为缺少结构化 evidence 导致误判？
8. 是否因为 threshold 把边界分数错误二值化？
```

建议使用以下归因标签进行人工复核：

```text
judge_reasoning_error
rubric_interpretation_error
gold_or_reference_ambiguity
benchmark_adapter_error
missing_structured_evidence
claim_score_inconsistency
threshold_or_anchor_mismatch
unknown
```

这些标签是分析用标签，不应直接写回 production feedback 或 benchmark knowledge，除非完成复核。

---

## 12. 优先级建议

### P0：人工复核 15 条 badcase

优先顺序：

1. `confidence >= 0.9` 的 badcase；
2. `status = contradictory` 的 4 条；
3. claims 与 score 明显方向不一致的 badcase；
4. HealthBench 的 safety/context-seeking case；
5. AgenticCoding 的 tool/rule checklist case。

人工复核结果需要区分：

```text
Judge 错
```

```text
Gold/rubric 有歧义
```

```text
adapter 丢失了必要结构
```

```text
score aggregation 错
```

### P1：二元 rubric 使用真正的离散 anchors

不要继续依赖：

```text
自由文本 anchors + score >= 0.5
```

应测试：

```text
score_anchors = [0.0, 1.0]
```

并保存：

```text
selected_anchor
scoring_mode
```

### P1：增加 claims-score consistency audit

对每条结果做离线检查：

- claims 全部支持但 score 为 0；
- 存在明确否定 claim 但 score 为 1；
- `contradictory` status 与单极端 score 不匹配；
- claims 的 evidence_refs 与最终 judgment evidence_refs 不一致。

### P1：结构化 AgenticCoding trajectory

将 trajectory 拆成：

```text
tool_call
tool_result
file_read
file_write
test_run
assistant_claim
```

并转换为 `EvidenceRecord`，使 Judge 能够查询：

```text
工具名称
工具参数
调用顺序
工具结果
文件变化
测试结果
最终声明
```

### P2：对 60 条进行重复与扰动 replay

固定当前输入，至少运行：

```text
3 repeats
```

并增加：

```text
order_shuffle
trace_lengthen
irrelevant_evidence_addition
```

用于判断当前 badcase 是：

```text
稳定错误
```

还是：

```text
单次随机漂移
```

---

## 13. 当前结论

本轮 60 条 pilot 的可复现结论是：

```text
Judge scoring success: 60/60
Binary accuracy: 45/60 = 75%
Badcase: 15/60 = 25%
```

按 benchmark：

```text
HealthBench: 13/20 = 65%
RuVer DeepResearch: 17/20 = 85%
RuVer AgenticCoding: 15/20 = 75%
```

但真正值得关注的不是单一 accuracy，而是以下结构性现象：

1. false negative 为 11 条，初步表现出偏严格倾向；
2. 15 条 badcase 中 14 条为高置信错误；
3. HealthBench 的错误集中在医学回答完整性、安全性和 context-seeking 边界；
4. DeepResearch 的主要风险是事实型 rubric 的 coverage 与事实核验边界；
5. AgenticCoding 的主要风险是 trajectory 未结构化，以及 tool/checklist 语义难以从长文本稳定抽取；
6. 部分 claims 与最终 score 可能不一致；
7. 当前空 EvidenceCatalog 使得 evidence retrieval error 与 reasoning error 无法分离。

因此最准确的总体判断是：

> 当前 AgentEval Judge 的调用链已经能够稳定执行，但在 rubric 边界、结构化证据和最终 score 一致性方面仍存在明显 badcase。下一步应先完成 15 条 badcase 的人工归因和 claims-score consistency audit，再进行 rubric 或 Judge prompt 修改。

本报告不建议直接根据这 60 条结果修改 production Judge，也不建议把三个 benchmark 的结果简单合并为一个无条件的全局准确率。
