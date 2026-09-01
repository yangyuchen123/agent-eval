# 外部 Judge 方法与现有 AgentEval 的相容性、互斥性和插入位置

日期：2026-08-31  
状态：设计审计文档。本文只说明如何引入外部方法用于消融实验和数据分析，**不修改当前生产 Judge，不安装外部依赖，不运行新的 Harbor/Pi 或 Judge 实验**。

---

## 1. 文档目标

当前 AgentEval 已经具备以下核心结构：

```text
Benchmark / historical fixture
        ↓
Case / MetaCase
        ↓
Rubric / rubric question
        ↓
EvidenceSnapshot / EvidenceProvider
        ↓
QuestionJudgeService
        ↓
QuestionJudgment
        ↓
AgentEval Runner / SkillResult / CaseEvidence
        ↓
Gold comparison / metrics / replay report
```

现在希望引入外部研究中的方法，用于：

- Judge reliability 消融；
- rubric granularity 消融；
- calibration head；
- uncertainty calibration；
- trajectory evaluation；
- evidence perturbation；
- badcase 和稳定性数据分析。

核心原则：

> 引入的是方法和实验变量，不是复制一套新的 Judge Harness、Gold 系统、Evidence 系统或 orchestrator。

外部方法必须被放入现有的：

```text
MetaEvalRunner
EvidenceSnapshot
QuestionJudgeService
score_anchors
GoldJudgment
metrics
report
```

之内。

---

## 2. 当前系统的插入层级

当前系统可以分成七个插入层：

```text
L0  Fixture / benchmark adapter
L1  Case normalization
L2  Rubric / question construction
L3  Evidence snapshot / perturbation
L4  Judge execution
L5  Calibration / decision mapping
L6  Gold comparison / metrics / report
```

各层职责：

| 层 | 当前职责 | 典型代码/数据 |
|---|---|---|
| L0 | 从 HealthBench、RuVerBench、Octagon 等来源读取材料 | benchmark-specific pilot scripts、fixture files |
| L1 | 统一为 `Case`/`MetaCase` | `src/agenteval/protocols.py`、`src/agenteval/meta_eval/` |
| L2 | 生成一个或多个 rubric question 及 anchors | `src/agenteval/meta_eval/process_rubric.py`、`src/agenteval/rubrics.py` |
| L3 | 构造证据集合和扰动版本 | `EvidenceSnapshot`、`perturbations.py` |
| L4 | 运行 Judge | `judge/src/agentjudge/service.py`、`QuestionJudgeService` |
| L5 | 将 raw score 转换为 calibrated score 或最终 decision | 当前主要是 `score >= 0.5`，尚未形成独立 calibration head |
| L6 | 与 Gold 对比、统计、报告 | `meta_eval/metrics.py`、`MetaEvalRunner`、各 pilot metrics |

建议的总体插入方式：

```text
外部方法
→ 映射到一个已有层
→ 通过 experiment manifest 作为实验条件
→ 输出进入已有 result/provenance/metrics
```

不要将外部方法直接嵌进 `QuestionJudgeService` 的主逻辑，除非该方法本身就是 Judge prompt 或 Judge 输出协议的一部分。

---

## 3. 总体相容性分类

| 方法 | 主要用途 | 建议插入层 | 与现有系统关系 | 是否可以直接进入生产 |
|---|---|---|---|---|
| Judge Reliability Harness / JRH 思路 | 扰动、重复、可靠性报告 | L3 + L6 | 高度相容，现有系统已有大部分能力 | 否，先作为 meta-eval protocol |
| RubricEval 思路 | rubric taxonomy、难度分层、rubric-level 分析 | L0 + L2 + L6 | 相容，但不能替换现有 rubric schema | 否，先作为 metadata/stratification |
| SAJA 类 calibration head | raw Judge 输出校准 | L5 | 相容，但会改变 raw score 到 decision 的映射 | 否，先作为 candidate post-processor |
| Conformal Judge 思路 | prediction interval、不确定性和 abstention | L5 + L6 | 相容，但要求独立 calibration set | 否，先作为 uncertainty layer |
| JudgeLM 的 reference/swap 思路 | position bias、reference support、format bias | L2 + L3 | 相容，但 reference 不能变成隐含知识库 | 否，作为 controlled ablation |
| AgentRewardBench 思路 | trajectory 多维质量标签 | L1 + L3 + L2 | 相容，但要求结构化 runtime evidence | 否，先应用于 AgenticCoding replay |

---

# 4. Judge Reliability Harness / JRH 思路

## 4.1 方法要解决什么问题

JRH 类方法解决的不是“如何让 Judge 多想几轮”，而是建立：

```text
gold fixture
→ controlled perturbation
→ judge replay
→ gold comparison
→ reliability report
```

典型实验变量包括：

- label flip；
- format variation；
- paraphrase；
- verbosity；
- repeated sampling；
- order swap；
- cost/latency；
- confidence interval。

## 4.2 与现有 AgentEval 的相容性

### 高度相容的部分

现有系统已经有：

```text
EvidenceSnapshot
MetaEvalRunner
reorder()
lengthen()
remove()
judgments.jsonl
metrics.json
META_EVAL_REPORT.md
```

因此没有必要复制一个 JRH runner。

建议直接复用：

```text
src/agenteval/meta_eval/runner.py
src/agenteval/meta_eval/perturbations.py
src/agenteval/meta_eval/metrics.py
```

并将外部方法中更完整的实验分类、置信区间和报告字段接入现有 meta-eval 输出。

### 不完全相容的部分

现有 perturbation 主要针对：

```text
runtime evidence order
trace length
```

尚未统一覆盖：

```text
response paraphrase
format variation
irrelevant evidence injection
duplicate evidence
contradictory evidence
tool-output truncation
```

这些属于能力扩展，不需要新建 perturbation 系统，只需要增加已有 `EvidenceSnapshot` transform 或输入 transform。

## 4.3 与现有模块的互斥点

不要同时引入两个独立的：

```text
repeat runner
perturbation registry
metrics schema
report generator
```

否则会出现：

- 同一 case 使用不同 repeat 定义；
- 同一扰动使用不同 seed；
- metrics 无法横向比较；
- provenance 分裂。

## 4.4 插入位置

建议插入：

```text
L3：EvidenceSnapshot / perturbation
L6：MetaEvalRunner metrics/report
```

不插入：

```text
QuestionJudgeService 主判断逻辑
```

推荐数据流：

```text
Frozen fixture
→ perturbation transform
→ EvidenceSnapshot'
→ QuestionJudgeService
→ QuestionJudgment
→ existing metrics
```

## 4.5 适合的消融

```text
A0 none
A1 order_shuffle
A2 trace_lengthen
A3 irrelevant_evidence_addition
A4 evidence_removal
A5 duplicate_evidence
A6 contradiction_injection
A7 paraphrase / format variation
```

每个实验都必须记录：

```json
{
  "perturbation_id": "order_shuffle",
  "seed": 20260831,
  "parent_snapshot_digest": "...",
  "child_snapshot_digest": "...",
  "changed_fields": ["evidence_order"],
  "judge_result_ref": "..."
}
```

## 4.6 结论

```text
相容性：高
复用重点：MetaEvalRunner + EvidenceSnapshot + metrics
真正缺口：扰动类型统一、bootstrap/CI、报告字段
互斥点：不要复制 JRH runner
插入层：L3、L6
```

---

# 5. RubricEval 思路

## 5.1 方法要解决什么问题

RubricEval 类方法关注：

```text
一个 rubric item 是否容易被正确判断
```

核心可借鉴内容不是外部系统本身，而是：

- rubric-level 作为基本分析单位；
- rubric taxonomy；
- difficulty stratification；
- easy/hard 分层；
- rubric complexity 与 Judge accuracy 的关系；
- rubric-level badcase taxonomy。

## 5.2 与现有 AgentEval 的相容性

现有三个 pilot 已经采用：

```text
一个 response/trajectory
+ 一个 rubric item
→ 一个 QuestionJudge
```

这与 rubric-level meta-eval 高度相容。

当前可直接复用：

```text
question_id
rubric_question
Gold label
category
case metadata
```

现有 `GoldJudgment` 也已经能够保存：

```text
expected_score
expected_status
expected_stratum
rubric_boundary_notes
positive_evidence_refs
negative_evidence_refs
```

## 5.3 需要补充的 metadata

建议为每个 rubric item 增加分析 metadata，而不是修改 rubric 的核心语义：

```json
{
  "rubric_semantic_type": "binary_coverage",
  "rubric_difficulty_stratum": "hard",
  "requires_multi_hop_reasoning": true,
  "requires_negative_evidence": false,
  "requires_external_knowledge": true,
  "requires_runtime_trace": false,
  "rubric_complexity": {
    "condition_count": 2,
    "exception_count": 1,
    "scope_count": 1
  }
}
```

这些字段是：

```text
分析 metadata
```

不是：

```text
Judge 隐式规则
```

## 5.4 与现有模块的互斥点

RubricEval taxonomy 不应替换：

```text
AgentEval rubric question schema
```

也不应把外部难度标签直接当作 Gold label。

特别注意：

```text
hard split
≠
当前 Judge 一定更难
```

外部 benchmark 的 hard 标记是数据集属性，需要和本系统实际 observed difficulty 分开保存：

```text
source_difficulty = hard
observed_judge_difficulty = measured_from_gold
```

## 5.5 插入位置

建议插入：

```text
L0：benchmark adapter / fixture metadata
L2：rubric question metadata
L6：按 taxonomy 和 difficulty 分组统计
```

不插入：

```text
QuestionJudgeService 内部 prompt 逻辑
```

除非将 rubric taxonomy 明确作为一个实验变量。

## 5.6 适合的消融

```text
B0 原始 rubric
B1 rubric 拆分为独立 criterion
B2 binary vs graded semantic type
B3 concise anchors vs verbose anchors
B4 explicit negative criterion vs implicit negative criterion
B5 one-hop vs multi-hop rubric
B6 presence/coverage vs correctness rubric
```

需要报告：

```text
accuracy
balanced accuracy
F1
MAE
rubric-level error rate
case-level aggregate error
confidence calibration
```

## 5.7 结论

```text
相容性：高
复用重点：单 rubric QuestionJudge、GoldJudgment、分层 metrics
真正缺口：rubric semantic taxonomy、difficulty metadata
互斥点：不能把外部 hard 标签当作 AgentEval Gold
插入层：L0、L2、L6
```

---

# 6. SAJA 类 calibration head

## 6.1 方法要解决什么问题

当前 AgentEval 的决策近似为：

```text
Judge raw score
→ score >= 0.5
→ binary decision
```

SAJA 类方法的核心思路是：

```text
Judge raw output + structured features
→ lightweight calibration head
→ calibrated probability / score
```

可使用的现有 Judge 输出字段包括：

```text
score
confidence
status
claims
missing_evidence
contradictions
evidence_refs
```

## 6.2 与现有 AgentEval 的相容性

相容，但它属于：

```text
Judge 之后的 calibration/post-processing
```

不是另一个 Judge。

当前 `QuestionJudgment` 已有足够的原始字段作为 candidate features：

```json
{
  "raw_score": 0.55,
  "model_confidence": 0.91,
  "status": "partially_supported",
  "claim_count": 4,
  "supported_claim_count": 2,
  "contradiction_count": 1,
  "missing_evidence_count": 2,
  "evidence_ref_count": 0
}
```

## 6.3 当前系统的真正缺口

当前缺少独立的：

```text
calibration dataset
calibration fit
calibration artifact
calibrated inference
```

还缺少明确区分：

```text
raw_score
calibrated_score
final_decision
```

## 6.4 与现有模块的互斥点

Calibration head 不应：

- 修改原始 `QuestionJudgment.score`；
- 覆盖原始 Judge output；
- 把校准结果写回 Gold；
- 和 Gold 使用同一批数据拟合、再报告同一批数据的准确率；
- 在没有独立 calibration split 时声称泛化提升。

必须保存：

```json
{
  "raw_score": 0.35,
  "calibrated_score": 0.61,
  "decision_threshold": 0.5,
  "calibrator_id": "...")
}
```

## 6.5 插入位置

建议新增一个**薄的离线 post-processor**，插在：

```text
L4 Judge execution
→ L5 calibration
→ L6 Gold comparison
```

推荐逻辑：

```text
QuestionJudgment
→ feature extractor
→ calibrator candidate
→ calibrated judgment view
→ metrics
```

不要把 calibration head 放进：

```text
judge/src/agentjudge/service.py
```

因为这样会让原始 Judge 与实验性 calibration 耦合。

## 6.6 适合的消融

```text
C0 raw score + fixed threshold
C1 Platt/logistic calibration
C2 isotonic calibration
C3 raw score + confidence
C4 raw score + status
C5 raw score + claims/evidence features
C6 rubric-category-specific calibrator
C7 global calibrator vs per-domain calibrator
```

必须使用数据切分：

```text
calibration split
→ fit calibrator
validation/test split
→ report result
```

## 6.7 结论

```text
相容性：高
复用重点：QuestionJudgment 输出、Gold comparison、existing metrics
真正缺口：独立 calibration artifact 和 split
互斥点：不能覆盖 raw score，不能用 test Gold 拟合
插入层：L5
```

---

# 7. Conformal Judge / uncertainty layer

## 7.1 方法要解决什么问题

当前 Judge 的 `confidence` 是模型自报值：

```text
confidence = LLM self-report
```

它不等于经过 Gold 校准的 correctness probability。

Conformal 类方法提供的是：

```text
raw score
→ calibration set
→ prediction interval / set / abstention
```

例如：

```json
{
  "raw_score": 0.72,
  "prediction_interval": [0.48, 0.84],
  "decision_threshold": 0.5,
  "abstain": true
}
```

## 7.2 与现有 AgentEval 的相容性

相容，但它和 SAJA calibration head 不是同一个模块：

| 模块 | 主要输出 |
|---|---|
| Calibration head | calibrated scalar score/probability |
| Conformal layer | interval/set/abstention decision |

两者可以串联：

```text
raw Judge
→ calibration head
→ conformal interval
→ accept / review / abstain
```

也可以分别做消融：

```text
raw Judge
→ conformal interval
```

## 7.3 当前系统的真正缺口

缺少：

- 独立 calibration Gold；
- nonconformity score 定义；
- coverage/validity report；
- abstention policy；
- human review routing。

## 7.4 与现有模块的互斥点

Conformal layer 不应：

- 把 interval 当作 Judge 原始 score；
- 把 abstain 自动当作 false；
- 将未校准的 `confidence` 直接作为 conformal input；
- 在同一 Gold 数据上拟合并评测 coverage；
- 用 prediction interval 替代 evidence/claims。

它回答的是：

```text
当前结果有多不确定？
```

不是：

```text
为什么 rubric 满足/不满足？
```

## 7.5 插入位置

建议插入：

```text
L5：calibrated uncertainty
L6：coverage / abstention / review metrics
```

不插入：

```text
EvidenceProvider
QuestionJudgeService 内部 reasoning
GoldJudgment schema 的核心字段
```

## 7.6 适合的消融

```text
U0 no uncertainty layer
U1 self-reported confidence only
U2 calibrated probability
U3 conformal interval
U4 interval-crosses-threshold → abstain
U5 abstention → second judge/human review
```

报告：

```text
coverage
interval width
selective accuracy
abstention rate
risk-coverage curve
review workload
```

## 7.7 结论

```text
相容性：中高
复用重点：Gold split、QuestionJudgment、review routing
真正缺口：独立 uncertainty calibration 协议
互斥点：不能把 abstain 当成错误，不能使用 self-confidence 代替 calibration
插入层：L5、L6
```

---

# 8. JudgeLM 的 reference support / swap 思路

## 8.1 方法要解决什么问题

这类方法主要用于分析和缓解：

- position bias；
- order bias；
- format bias；
- reference support 的影响；
- reference presence/absence 的影响。

在当前单回答 rubric Judge 中，可转化为：

```text
same case
→ evidence/order/reference condition changes
→ compare judgment
```

## 8.2 与现有 AgentEval 的相容性

高度相容于现有：

```text
EvidenceSnapshot reorder
Question prompt construction
MetaEvalRunner
```

对于 pairwise 或 multi-candidate judging，当前系统没有统一 pairwise data contract，因此不能直接把 pairwise JudgeLM 代码塞进当前 single-response QuestionJudge。

## 8.3 可直接引入的部分

可以借鉴：

```text
order swap
reference support on/off
format normalization
candidate position balance
```

在当前系统中对应：

```text
Evidence order shuffle
rubric/reference inclusion ablation
response formatting ablation
```

## 8.4 与现有模块的互斥点

Reference support 有三个边界：

### 不能把 Gold 当作 Judge 输入

如果把正确答案或人工标签直接放进 Judge prompt，测到的是：

```text
reference-assisted judging
```

不是普通 Judge accuracy。

### 不能把 reference support 和 Gold evaluation 混在同一条件名下

必须明确：

```text
reference_condition = none / rubric_only / exemplar / answer_reference
```

### 不能把 order swap 与 reasoning 改动同时进行

否则无法归因。

## 8.5 插入位置

建议插入：

```text
L2：Question prompt / reference condition
L3：Evidence/order perturbation
L6：position consistency metrics
```

不插入：

```text
Gold schema
QuestionJudgment schema
```

## 8.6 适合的消融

```text
J0 original order
J1 evidence order shuffle
J2 candidate/reference order swap
J3 rubric only
J4 rubric + exemplar
J5 rubric + reference answer
J6 format-normalized response
J7 raw response formatting
```

报告：

```text
position flip rate
order consistency
score delta
status flip rate
evidence selection delta
```

## 8.7 结论

```text
相容性：高（single-response order/evidence ablation）
相容性：中（pairwise reference judging）
真正缺口：pairwise input schema、reference condition provenance
互斥点：不能把 reference-assisted 条件当普通 accuracy
插入层：L2、L3、L6
```

---

# 9. AgentRewardBench 的 trajectory evaluation 思路

## 9.1 方法要解决什么问题

Agent trajectory Judge 不应只回答：

```text
任务最后成功了吗？
```

还应区分：

- goal completion；
- side effects；
- repetitiveness；
- unnecessary actions；
- safety；
- process quality；
- evidence quality。

## 9.2 与现有 AgentEval 的相容性

目标高度相容于现有 AgentEval 的多问题 rubric：

```text
task_understanding
required_action_execution
result_validation
observed_failure_handling
completion_claim_integrity
```

但当前 AgenticCoding pilot 的 trajectory 仍然是：

```text
trajectory.messages
→ serialized agent_output
```

还没有完全转换成结构化 `EvidenceRecord`。

因此当前只能做：

```text
trajectory-text checklist judging
```

还不能完整做：

```text
structured trajectory evidence judging
```

## 9.3 推荐引入的 trajectory dimensions

可以映射到现有 `rubric_question`：

| 外部 trajectory 维度 | AgentEval question |
|---|---|
| goal completion | `required_action_execution` / task-level result |
| side effects | 新的 diagnostic question 或 rubric metadata |
| repetitiveness | 新的 diagnostic question |
| unnecessary action | 新的 diagnostic question |
| safety | `completion_claim_integrity` 或单独 safety question |
| validation | `result_validation` |
| failure recovery | `observed_failure_handling` |

不建议马上增加所有问题。应先选择 1~2 个已有真实 Gold 可支持的维度。

## 9.4 当前系统的真正缺口

缺少：

```text
trajectory → structured EvidenceRecord[]
```

建议至少拆成：

```text
user_message
assistant_message
tool_call
tool_result
file_read
file_write
test_run
error_event
final_claim
```

每条 evidence 应保留：

```json
{
  "evidence_id": "msg-42",
  "source": "ruverbench.agenticcoding",
  "event_type": "tool_result",
  "evidence_class": "direct_runtime_event",
  "claim_strength": "direct",
  "tool_name": "pytest",
  "content": {
    "text": "...",
    "instance_id": "...",
    "check_id": "..."
  }
}
```

## 9.5 与现有模块的互斥点

不能同时把：

```text
完整 serialized trajectory
```

和：

```text
结构化 EvidenceRecord
```

称作同一个 evidence condition。

至少要在 manifest 中区分：

```text
trajectory_input_mode = serialized_text
trajectory_input_mode = structured_evidence
trajectory_input_mode = hybrid
```

否则无法判断准确率变化到底来自：

- anchor 改动；
- evidence representation 改动；
- Judge reasoning 改动。

## 9.6 插入位置

建议插入：

```text
L1：trajectory adapter
L3：EvidenceSnapshot / EvidenceProvider
L2：trajectory-specific rubric questions
L6：dimension-level trajectory metrics
```

不建议插入：

```text
Pi/Harbor runtime
```

第一阶段直接 replay 已冻结的 RuVerBench trajectory。

## 9.7 适合的消融

```text
T0 serialized full trajectory
T1 structured evidence records
T2 structured evidence + query retrieval
T3 remove tool results
T4 remove file events
T5 shuffle independent events
T6 add irrelevant events
T7 truncate long tool output
```

## 9.8 结论

```text
相容性：高，但依赖结构化 evidence
复用重点：MetaCase、EvidenceSnapshot、EvidenceProvider、多问题 rubric
真正缺口：trajectory adapter、event normalization、runtime evidence digest
互斥点：serialized text 与 structured evidence 必须分条件
插入层：L1、L2、L3、L6
```

---

# 10. 方法之间的组合关系

## 10.1 推荐组合

### 组合 A：可靠性基础层

```text
JRH-style perturbation
+ existing MetaEvalRunner
+ Gold comparison
```

用途：

```text
重复一致性
证据顺序鲁棒性
trace 长度鲁棒性
```

### 组合 B：Rubric granularity

```text
Rubric semantic taxonomy
+ 2/3/5 anchor ablation
+ Gold comparison
```

用途：

```text
rubric semantic type
↔
optimal score resolution
```

### 组合 C：Calibration

```text
raw QuestionJudgment
+ SAJA-style calibration head
+ conformal uncertainty layer
```

用途：

```text
raw score calibration
selective acceptance
human review routing
```

### 组合 D：Trajectory evidence

```text
AgentRewardBench dimensions
+ structured trajectory EvidenceRecord
+ JRH perturbation
```

用途：

```text
trajectory evidence retrieval
process quality
side effect
failure recovery
```

## 10.2 不推荐的组合

### 不推荐一开始同时改四件事

不要把以下改动放在一个实验里：

```text
anchor count
rubric wording
EvidenceRecord format
calibration head
```

否则任何 accuracy 变化都无法归因。

### 不推荐把外部系统整体嵌入

不要同时引入：

```text
JRH runner
外部 RubricEval runner
外部 calibration service
外部 trajectory evaluator
```

这会产生：

- 第二套 cache；
- 第二套 Gold join；
- 第二套 report schema；
- 第二套 provenance；
- 运行结果不可比较。

### 不推荐把 calibration 直接塞进 Judge

应保留：

```text
raw Judge output
```

和：

```text
calibrated output
```

两个版本。

---

# 11. 推荐的统一实验条件结构

建议实验 manifest 使用如下逻辑字段：

```json
{
  "experiment_id": "EXP-judge-method-001",
  "hypothesis": "Rubric semantic granularity determines the useful score resolution.",
  "changed_component": "anchor_protocol",
  "changed_variable": {
    "anchor_levels": 5,
    "anchor_style": "qualitative"
  },
  "frozen_components": [
    "benchmark_cases",
    "responses_or_trajectories",
    "gold_labels",
    "judge_model",
    "judge_service",
    "evidence_snapshot",
    "adapter_version"
  ],
  "method_conditions": {
    "perturbation": "none",
    "reference_condition": "rubric_only",
    "trajectory_input_mode": "serialized_text",
    "calibration": "none",
    "uncertainty": "none"
  },
  "fixture_set": [
    "healthbench-pilot-v1-20",
    "ruver-deepresearch-pilot-v1-20",
    "ruver-agenticcoding-pilot-v1-20"
  ],
  "gold_policy": "external_reference_frozen",
  "metrics": [
    "accuracy",
    "balanced_accuracy",
    "f1",
    "gold_mae",
    "confidence_calibration"
  ],
  "promotion_status": "fast_only"
}
```

注意：

```text
method_conditions
```

是实验元数据，不是新的 Judge 输入 schema。

---

# 12. 推荐的实施顺序

## Phase 0：只读兼容性和 provenance

目标：

```text
不改变 Judge
```

完成：

- 为现有 60 条 pilot 补齐 method condition metadata；
- 保存 raw result 与 derived metric；
- 区分 benchmark label、physician label、checklist label；
- 固定输入 digest。

验收：

```text
任何结果可以回溯到原始 case、rubric、Gold、model 和 adapter。
```

## Phase 1：JRH-style perturbation replay

复用已有：

```text
MetaEvalRunner
EvidenceSnapshot
perturbations
metrics
```

先完成：

```text
repeat
order_shuffle
trace_lengthen
irrelevant_evidence_addition
```

验收：

```text
不运行 Harbor/Pi 即可完成 stability/robustness 报告。
```

## Phase 2：Rubric semantic taxonomy

给当前 60 条 rubric/check 做人工或规则辅助标注：

```text
binary_coverage
binary_protocol
factual_numeric
factual_claim
logic_causal
graded_quality
safety_completeness
process_quality
```

验收：

```text
可以按 semantic type 比较 2 档和 5 档，而不是只按 benchmark 比较。
```

## Phase 3：2/5 anchor 的 threshold analysis

不重新生成 benchmark，只对固定结果做：

```text
τ = 0.25 / 0.5 / 0.75
```

分析：

```text
5-level native score
→ threshold
→ binary decision
```

验收：

```text
区分 resolution gain 与 decision-threshold shift。
```

## Phase 4：SAJA-style calibration head

使用独立 Gold split：

```text
fit split
→ calibrator
held-out split
→ report
```

验收：

```text
raw score 与 calibrated score 同时存在；不污染原始 Judge result。
```

## Phase 5：Conformal uncertainty

在 calibration head 之后增加：

```text
interval
abstention
selective metrics
```

验收：

```text
可以报告 coverage、interval width 和 risk-coverage。
```

## Phase 6：AgenticCoding structured evidence

将冻结 trajectory 转换成 `EvidenceRecord[]`，再对比：

```text
serialized text
vs
structured evidence
```

验收：

```text
能够区分 retrieval failure、evidence selection failure 和 reasoning failure。
```

---

# 13. 当前最小插入清单

| 优先级 | 插入点 | 最小工作 | 不改什么 |
|---|---|---|---|
| P0 | L6 | 统一 experiment/method provenance | 不改 Judge |
| P0 | L3/L6 | 复用 perturbation + stability metrics | 不新建 runner |
| P1 | L0/L2/L6 | rubric semantic taxonomy | 不替换 rubric schema |
| P1 | L5 | raw score calibration post-processor | 不覆盖 raw score |
| P2 | L5/L6 | uncertainty/abstention layer | 不把 abstain 当 false |
| P2 | L1/L3 | coding trajectory structured evidence adapter | 不改 Harbor/Pi |
| P3 | L2/L3/L6 | reference/order bias ablation | 不把 reference-assisted 当普通条件 |

---

# 14. 研究结论边界

引入这些方法后，应分别报告三类结论：

## 14.1 Judge correctness

```text
与 Gold 的 agreement
```

指标：

```text
accuracy
balanced accuracy
F1
MAE
```

## 14.2 Judge stability/robustness

```text
相同输入重复或轻微扰动后是否保持判断
```

指标：

```text
repeat agreement
score std
status flip rate
position flip rate
evidence overlap
```

## 14.3 Judge calibration/uncertainty

```text
raw score/confidence 是否具有统计意义
```

指标：

```text
calibration error
Brier score
interval coverage
interval width
risk-coverage
abstention rate
```

这三类不能混成一个总分。

---

# 15. 最终建议

当前最值得引入的不是外部代码，而是以下方法级 primitive：

```text
JRH-style perturbation protocol
Rubric semantic taxonomy
SAJA-style calibration post-processor
Conformal uncertainty layer
structured trajectory evidence
```

推荐顺序：

```text
已有 replay/Gold
→ perturbation reliability
→ rubric semantic stratification
→ threshold analysis
→ calibration head
→ uncertainty
→ structured trajectory evidence
```

最重要的相容性判断：

1. **JRH 思路与现有 MetaEvalRunner 高度相容**，不应复制外部 runner；
2. **RubricEval 思路与当前单 rubric Judge 结构高度相容**，应作为 taxonomy/分层 metadata；
3. **SAJA calibration 应放在 Judge 之后**，不能改变 raw judgment；
4. **Conformal 层应放在 calibration 之后或作为独立 uncertainty ablation**；
5. **JudgeLM 的 swap/reference 应作为可控条件**，不能把 reference-assisted 结果和普通 Judge 混在一起；
6. **AgentRewardBench 思路要求先结构化 trajectory evidence**，否则只能测试长文本阅读，不是完整 runtime evidence judging。

最终目标不是构建更复杂的 Judge，而是得到一套可归因的实验链：

```text
frozen Gold fixture
→ one controlled method change
→ raw Judge result
→ optional calibrated/uncertainty view
→ reliability metrics
→ badcase attribution
```

一句话总结：

> 外部方法应该作为现有 AgentEval 的可插拔实验条件和分析层引入，而不是作为第二套评测系统；先复用现有 replay/evidence/Gold 基础设施，再逐步加入 perturbation、rubric taxonomy、calibration、uncertainty 和结构化 trajectory evidence。

---

# 16. 逐条插入卡片（当前系统相容/互斥审计）

本节把每个外部方法压缩成可执行的“插入卡片”。其中“相容”表示可以在不改变现有主评分协议的情况下复用；“互斥”表示不能直接叠加，必须保持为独立实验条件。

## 16.1 JRH-style reliability / perturbation

**目标问题**：同一冻结输入在重复、顺序、格式或证据扰动下是否保持判断。

**现有可复用模块**：

- `MetaEvalRunner`：重复运行、按 case/question/judge/perturbation 分组；
- `EvidenceSnapshot`：冻结证据并生成变体；
- `perturbations.py`：已有 evidence reorder、lengthen 等变换；
- `metrics.py` / `report.py`：稳定性、检索和分数汇总。

**插入位置**：

```text
MetaCase.evidence
  → L3 EvidenceSnapshot / perturbation
  → L4 QuestionJudgeService
  → L6 stability / robustness metrics
```

**相容性**：高。它是实验协议，不是第二个 Judge。

**互斥点**：

- 不复制 JRH 的 runner、Gold schema 或报告系统；
- 不把 perturbation 后的结果当作新的独立 Gold case；
- 一次实验不得同时改变 rubric anchor、judge prompt 和 evidence order，否则无法归因；
- repeat 只能用于稳定性，不能用 majority vote 结果替换单次 Judge 的原始输出。

**最小落地**：将每个扰动条件写入现有 meta-eval manifest，并在现有 `JudgmentObservation.provenance` 中保存变换名、seed 和 snapshot digest。

## 16.2 RubricEval-style rubric taxonomy / hard split

**目标问题**：不同 rubric 语义类型和难度层级下，Judge 的错误是否不同。

**现有可复用模块**：

- `RubricQuestion` / `score_anchors`；
- `meta_eval/gold.py` 的 Gold judgment；
- `meta_eval/taxonomy.py` 的 case/rubric 分类能力；
- 现有按 benchmark 的 metrics/report。

**插入位置**：

```text
benchmark adapter
  → L0 rubric semantic metadata
  → L2 question construction
  → L6 stratified metrics / badcase analysis
```

**相容性**：高，但只应增加 metadata，不替换 Gold 或 rubric 核心字段。

**互斥点**：

- 外部 `easy/hard` 标签不能直接改写 Gold；
- benchmark-level 标签不能被解释为每条 rubric 的 observed difficulty；
- taxonomy 与 anchor-level 实验必须分开记录；
- 不把 “hard subset accuracy” 当作 Agent 真实能力难度，除非 runtime、verifier 和 evaluator 均通过 qualification。

**最小落地**：为每条 question 增加可选的 `rubric_semantic_type`、`source_difficulty`、`taxonomy_version`，并让报告按这些字段分层。

## 16.3 SAJA-style calibration head

**目标问题**：Judge raw score 与 Gold 事件之间是否存在可学习的系统性偏差。

**现有可复用模块**：

- `QuestionJudgment` 的 raw score/status/confidence/evidence 字段；
- `GoldJudgment`；
- 现有 score-to-binary decision 逻辑；
- 现有 metrics/report。

**插入位置**：

```text
QuestionJudgment(raw)
  → L5 feature extraction / calibration post-processor
  → calibrated view
  → L6 Gold comparison
```

**相容性**：高，前提是 calibration 是只读后处理。

**互斥点**：

- 不修改或覆盖原始 `QuestionJudgment.score`；
- 不将 calibrated score 写回 Gold；
- 不在同一批 test Gold 上拟合并报告 calibration gain；
- 不把 calibration head 当成新的 Judge；
- 不把不同 anchor prompt 的结果混合拟合为同一个 calibrator，除非实验明确把 prompt 作为 feature/condition。

**最小落地**：产生平行的 `calibrated_judgment`，至少保留 `raw_score`、`calibrated_score`、`decision_threshold`、`calibrator_id`、`fit_split_digest`。

## 16.4 Conformal / uncertainty layer

**目标问题**：Judge 何时应接受、拒绝或转人工，而不是强行输出二元结论。

**现有可复用模块**：

- raw/calibrated score；
- Gold calibration split；
- 现有 report/metrics；
- evidence sufficiency 与 status 字段。

**插入位置**：

```text
raw/calibrated judgment
  → L5 interval / prediction set / abstention
  → L6 coverage, width, risk-coverage
```

**相容性**：中高。它不改变证据和 Judge，但会增加最终决策状态。

**互斥点**：

- `abstain` 不能自动当作 negative；
- Judge 自报 `confidence` 不能冒充 conformal coverage；
- interval 计算必须使用独立 calibration data；
- coverage、selective risk 与普通 accuracy 必须分开报告。

**最小落地**：只增加 uncertainty artifact 和 report，不改变现有生产判决。

## 16.5 JudgeLM-style reference support / swap

**目标问题**：reference、候选顺序、格式变化是否造成 position/knowledge/format bias。

**现有可复用模块**：

- L2 rubric/reference prompt construction；
- L3 evidence/order perturbation；
- L4 Judge execution；
- L6 paired consistency metrics。

**插入位置**：

```text
RubricQuestion + reference_condition
  → L2 prompt condition
  → L3 order/evidence transform
  → L4 Judge
  → L6 position consistency
```

**相容性**：中高，适合作为 controlled ablation。

**互斥点**：

- reference-on 与 reference-off 必须是不同 condition；
- Gold label 不能作为 Judge prompt 的 reference；
- 不能同时改变 reference、anchor 文案和 evidence order；
- reference-assisted accuracy 不能与 rubric-only accuracy 合并成一个 headline。

**最小落地**：给现有 manifest 增加 `reference_condition`、`candidate_order`、`prompt_variant`，并复用现有 paired comparison。

## 16.6 AgentRewardBench-style trajectory dimensions

**目标问题**：Agent trajectory 除了最终成功率，还是否存在副作用、重复动作、恢复能力或证据质量问题。

**现有可复用模块**：

- Harbor/Pi 产生的 native session、ATIF 或 trajectory；
- `adapters/runtime_evidence.py`；
- `EvidenceRecord` / `EvidenceSnapshot`；
- runtime judge 与现有 trajectory adapter；
- 现有 rubric question / Gold comparison。

**插入位置**：

```text
frozen trajectory
  → L1 trajectory normalization
  → L3 EvidenceRecord[] / EvidenceSnapshot
  → L2 trajectory-specific rubric question
  → L4 Judge
  → L6 dimension metrics
```

**相容性**：中等。当前 AgenticCoding pilot 仍可能以 serialized trajectory 为主，结构化转换是必要前置步骤。

**互斥点**：

- 不能把结构化 EvidenceRecord 和原始 serialized trajectory 同时作为无标记输入；
- 不把 trajectory dimension score 自动合成为 task success；
- 不把 deterministic verifier 结果当作 process-quality Gold；
- 只有明确 evidence refs 的维度才可进入 evidence-recall 分析。

**最小落地**：先对冻结历史 trajectory 做离线 adapter，不修改 Harbor/Pi 和生产 AgentEval 主路径。

---

# 17. 关键修正：anchor prompt 与档位数量必须拆成两个实验因子

此前 2 档与 5 档结果只能说明某一组完整条件的差异，不能把提升归因于“档位数量”本身。Judge 的输出受至少两个独立变量影响：

```text
anchor_protocol = anchor_levels × anchor_semantics × anchor_wording
```

因此本系统必须分别记录：

| 因子 | 例子 | 解释 |
|---|---|---|
| `anchor_levels` | 2 / 5 | 输出分辨率；只说明有多少个可选分数 |
| `anchor_style` | binary / qualitative / continuum | 档位如何表达中间状态 |
| `anchor_wording_version` | v1 / v2 | 每个 anchor 的具体文字、正反例、边界说明 |
| `decision_threshold` | 0.25 / 0.5 / 0.75 | 从 ordinal score 映射到 binary verdict 的规则 |
| `rubric_semantic_type` | coverage / quality / process | rubric 的潜在语义粒度 |

## 17.1 推荐的消融矩阵

最小可归因矩阵为：

```text
同一 case、同一 evidence、同一 model、同一 Gold

A. anchor_levels: 2 vs 5
B. anchor_style: qualitative vs continuum
C. anchor_wording: old vs revised
D. threshold: τ ∈ {0.25, 0.50, 0.75}
```

优先顺序不是先扩大档位，而是：

1. 固定 2 档，比较旧/新 anchor wording；
2. 固定 5 档，比较旧/新 anchor wording；
3. 固定 wording，比较 2/5 档；
4. 对 5 档做 threshold sweep；
5. 按 rubric semantic type 分层。

这能区分：

```text
anchor wording gain
vs
resolution gain
vs
threshold shift
```

## 17.2 当前 60 条实验的解释边界

当前 60 条结果中，2 档与 5 档比较同时改变了输出档位/anchor 条件，因此不能写成：

> 五档 Judge 本身更准确。

更准确的表述是：

> 在冻结的 60 条跨 benchmark Gold case 上，5 档实验条件相较 2 档实验条件取得更高的最终二元判定指标；该差异可能来自 anchor wording、anchor semantics、档位数量或 binary threshold 的共同作用，尚未完成因子分解。

后续实验应将 `anchor_prompt_digest` 和 `anchor_levels` 作为两个独立 provenance 字段，并在 report 中同时显示 raw score 与 derived binary decision。

## 17.3 与现有系统的插入位置

不修改 `QuestionJudgeService` 主体。具体放置为：

```text
RubricQuestion.score_anchors
  → prompt builder / L2
  → QuestionJudgeService / L4
  → raw QuestionJudgment
  → threshold/calibration / L5
  → Gold metrics / L6
```

其中：

- anchor wording 属于 L2 prompt condition；
- anchor levels 属于 L2 score representation condition；
- threshold 属于 L5 decision mapping；
- accuracy 变化属于 L6 观测结果，不能反向证明是哪一个因子造成。

---

# 18. 最终逐条结论

| 方法 | 当前结论 | 首次插入位置 | 互斥边界 | 首次验收 |
|---|---|---|---|---|
| JRH-style | 可直接复用，主要是 protocol/metrics | L3/L6 | 不复制 runner；一次只改一个扰动因子 | historical fixture replay |
| RubricEval-style | 可作为 taxonomy/分层分析 | L0/L2/L6 | 不改 Gold；不把 hard 当 observed difficulty | 60 条按 rubric 类型分层 |
| SAJA-style | 可作为离线 calibration candidate | L5 | 不覆盖 raw score；fit/test 分离 | held-out calibration gain |
| Conformal | 可作为 uncertainty/abstention candidate | L5/L6 | 不把 abstain 当 false；需独立 calibration | coverage/risk-coverage |
| JudgeLM-style | 可作为 reference/position bias ablation | L2/L3/L6 | reference/G​​old/anchor 不混条件 | swap/reference paired report |
| AgentRewardBench-style | 可复用 trajectory dimensions，但需结构化 evidence | L1/L3/L6 | 不把 process score 等同 success | serialized vs structured replay |
| Anchor prompt study | 应优先于单纯档位比较 | L2/L5/L6 | wording/levels/threshold 必须分开 | factorized ablation |

本阶段不实施外部方法的生产接入。下一阶段若开始编码，优先顺序为：

```text
provenance / manifest
→ anchor wording × levels factorization
→ JRH-style replay metrics
→ rubric taxonomy
→ calibration post-processor
→ uncertainty
→ structured trajectory evidence
```

验收标准是每个外部方法都能回答：

1. 输入来自现有哪个 artifact 或 schema；
2. 插入现有哪一层；
3. 输出写入哪个现有 result/provenance/report；
4. 哪些现有模块保持不变；
5. 如何通过单因素消融证明它带来什么变化。

---

# 19. 方案冻结与下一阶段研究主线

根据当前评审，本方案不再继续横向增加新的 Judge 方法。后续重点从“收集更多方法”转为“用可归因的 factorial experiment 分离测量误差来源”。

## 19.1 保留并冻结的基础结构

以下设计作为当前 AgentEval 的稳定研究基础，不再重复设计第二套平行机制：

- L0-L6 分层；
- experiment manifest；
- anchor factorization；
- rubric semantic taxonomy；
- JRH-style perturbation protocol；
- structured `EvidenceRecord`；
- raw output 与 calibrated output 分离。

它们分别承担：

```text
L0/L1  fixture、benchmark、trajectory 的来源与标准化
L2     rubric、question、anchor、prompt condition
L3     evidence snapshot、oracle/扰动条件
L4     原始 Judge 执行
L5     threshold、calibration、uncertainty 后处理
L6     Gold 比较、稳定性、误差分解和报告
```

## 19.2 调整后的优先级

### 提前执行

1. **Structured trajectory evidence**
   
   先把冻结的 runtime trajectory 转换为结构化 `EvidenceRecord[]`，使 evidence access 成为可控实验变量，而不是把整段 serialized trace 直接交给 Judge。

2. **Oracle evidence condition**
   
   在同一 rubric 和同一 response 下，增加理想证据条件，用于估计 evidence access 对最终错误的影响。

3. **Rubric decomposition depth**
   
   将 rubric 拆成不同深度的 question/criterion 结构，用于判断错误来自 rubric representation，还是来自 Judge 的语义推断。

### 保持中后期

- SAJA-style calibration：先完成 raw score 与 decision 的基线和数据切分，再进行 calibration head；
- Conformal uncertainty：需要足够的独立 calibration data，不提前与核心 error decomposition 混合；
- Reference-assisted judging：作为后续 controlled ablation，不能在主实验中引入额外 reference confounder。

## 19.3 研究主假设

当前主线定义为：

> LLM Judge 的观测错误可以分解为 rubric representation error、evidence access error 和 semantic inference error；通过冻结其他条件并逐项替换，可以测量三者对最终 Gold disagreement 的相对贡献。

这里的“误差”是实验分析术语，不假设 Gold 有问题。默认将已有 Gold 视为评价参照，除非另有独立的标注审计证据。

## 19.4 最小 factorial experiment

对同一批冻结 Gold case，固定：

```text
benchmark case
response / trajectory
Gold label
Judge model/provider
Judge service version
sampling configuration
```

只改变以下三个因素：

| 因素 | 基线条件 | 对照条件 | 主要回答的问题 |
|---|---|---|---|
| Rubric representation | 原始 rubric | 分解/改写 rubric | rubric 表示是否造成误差 |
| Evidence access | 当前 evidence | oracle/完整结构化 evidence | Judge 是否因看不到证据而错 |
| Semantic inference protocol | 当前 anchor/prompt | 受控 anchor/decomposition 条件 | Judge 是否在证据充分时仍然推断错误 |

建议先做 2×2×2 的最小设计：

```text
R0/R1 × E0/E1 × I0/I1
```

其中：

```text
R0 = 原始 rubric representation
R1 = 受控 rubric decomposition
E0 = 当前可用 evidence
E1 = oracle/结构化完整 evidence
I0 = 当前 anchor/inference protocol
I1 = 单一受控 inference/anchor 改动
```

注意：`I1` 必须只改变 anchor/inference protocol，不能同时修改 rubric 或 evidence。若当前无法严格定义 `I1`，第一轮应先完成 `R × E` 的 2×2 实验，而不是强行扩展到 2×2×2。

## 19.5 推荐结果矩阵

每个 cell 至少报告：

```text
accuracy
balanced_accuracy
positive/negative F1
Gold MAE（适用时）
raw score distribution
binary decision
status flip rate
required evidence recall
selected evidence precision
```

并保存：

```text
experiment_id
factor_values
fixture_set
frozen_input_digests
rubric_digest
anchor_prompt_digest
evidence_snapshot_digest
judge_config_digest
result_digest
```

## 19.6 误差解释规则

不要只比较最终 accuracy。优先使用以下解释顺序：

1. **Evidence oracle 后恢复正确**：归因于 evidence access/selection 问题；
2. **Rubric 改写后恢复正确，但 oracle 不变**：归因于 rubric representation 问题；
3. **Rubric 和 evidence 均充分仍错误**：归因于 semantic inference 问题；
4. **多个条件均正确或均错误**：不能仅凭结果归因，进入 paired badcase review；
5. **多个因素同时变化**：该 case 不用于单因素归因。

该规则用于分析，不会自动修改生产 score 或 feedback。

## 19.7 明确暂缓的工作

当前不做：

- 引入更多外部 Judge framework；
- 复制外部项目的完整 orchestrator；
- 把 SAJA、Conformal、reference condition 同时加入主实验；
- 继续扩大 benchmark 数量而不先固定 error decomposition；
- 直接把 2 档 vs 5 档结果解释为档位数量的因果效果；
- 修改 Harbor/Pi 或生产 AgentEval 主评分路径。

下一阶段的完成标准不是“支持更多方法”，而是完成一组能够回答以下问题的冻结 replay：

```text
在 Gold、response、Judge 和其他输入不变时：
rubric 改变带来多少差异？
evidence 改变带来多少差异？
当两者都充分后，Judge 自身还剩多少 inference error？
```
