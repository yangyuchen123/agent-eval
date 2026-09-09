# Human-Rubric-Guided Rubric Generation Pipeline：MVP 方案

状态：MVP Phase 1 partially implemented；generation 尚未实施
版本：v0.2（2026-09-01）
适用范围：RuVerBench AgenticCoding、AgentEval rubric generation pilot

## 0. 方案目标与收敛原则

本方案不推翻原有方向，而是将其从“偏研究型完整框架”收敛为一个优先验证工程价值的最小可行方案。

核心目标：

> 对一个没有人工 rubric 的新 AgenticCoding task，利用 RuVerBench 中已有的人类 rubric 案例，为该 task 自动生成与 RuVer 人工评测习惯尽可能一致、可执行、可观测的 rubric。

本阶段首先回答一个应用问题：

> Task-specific human rubric retrieval 是否真的比简单方法更有价值？

因此第一阶段不追求一次性完成所有 feature、taxonomy、validator、alignment 和统计机制，也不预设 retrieval 一定获胜。

### 0.1 保持不变的原则

继续使用：

```text
New Task
→ Task Representation
→ RuVer Human Rubric Memory
→ Similar Task Retrieval
→ Rubric Generation
→ Minimal Validation
→ Held-out Evaluation
```

继续坚持：

- memory item = task + context + human rubric set；
- held-out self-exclusion 和 leakage protection；
- shared runner；
- frozen experiment manifest；
- 现有 B Judge 作为固定下游 evaluator；
- 不修改 Gold；
- 不修改 B Judge；
- 不新增 Judge protocol；
- 不把 generated rubric 写回同轮 retrieval memory；
- 不为每个条件复制新的 runner；
- 不运行 Harbor/Pi 来验证 rubric generation 本身。

### 0.2 本阶段明确不做

暂不实现：

- 复杂 learning-to-rank；
- latent intent model；
- adaptive rubric router；
- fine-tuning；
- RL；
- multi-agent debate；
- 复杂 semantic validator taxonomy；
- 自动生成 pseudo-Gold；
- 新 Judge protocol；
- 为每个 generated criterion 建立复杂的全量属性体系。

---

## 1. 当前系统中的插入位置

当前系统主链保持：

```text
EvalSystem / Harbor / Pi
    → frozen task + trajectory + artifact
    → AgentEval / Judge
    → score / evidence / feedback / KB
```

rubric generation 作为离线准备阶段插入：

```text
New Task
   ↓
Task Representation
   ↓
RuVer Human Rubric Memory
   ↓
Similar Task Retrieval
   ↓
Retrieval Quality Gate
   ↓
Rubric Generator
   ↓
Minimal Rubric Validator
   ↓
Generated Rubric Set
   ↓
existing B Judge（最后才调用）
```

### 1.1 现有能力与最小新增缺口

| 能力 | 当前状态 | MVP 处理方式 |
|---|---|---|
| RuVer task / checklist loader | RuVerBench 已有数据读取逻辑 | 复用字段语义，生成 task-level memory |
| AgentEval rubric/question 结构 | 已存在 | 生成结果只需兼容最小 rubric/question 输入 |
| Planner / Router | 已存在 | 本阶段不改；生成 rubric 作为下游输入 |
| B Joint Judge | 已存在并为生产默认 | 固定作为最后的 downstream evaluator |
| trajectory/artifact loader | 已存在 | 只用于 B Judge 验证，不参与第一阶段 retrieval quality 判断 |
| task-level human rubric memory | 尚无统一冻结产物 | MVP 首个实现缺口 |
| task representation | 部分由数据和 metadata 提供 | 只提取 7 个高价值字段 |
| retrieval | 尚无统一 rubric-generation 入口 | MVP 使用简单 semantic + metadata retrieval |
| retrieval quality gate | 尚无 | MVP 必须先做，阻止低质量 retrieval 进入 generation |
| rubric generator | 尚无稳定统一入口 | MVP 共享 generator，使用 A/B/C/D 条件配置 |
| minimal validator | 尚无本任务专用入口 | MVP 只做 5 类高价值检查 |
| N:M human/generated alignment | 尚无稳定统一机制 | 在 downstream 前实现最小人工/语义 alignment |
| experiment manifest | 已有实验管理标准 | 复用现有标准，不新增平台 |

### 1.2 与当前 B baseline 的关系

本 pipeline 不改变当前生产 B：

```text
B = joint multi-rubric + full task-level trajectory
```

生成 rubric 只会作为 B Judge 的输入之一，与人工 rubric 条件并列比较：

```text
trajectory + human rubric → B Judge
trajectory + generated rubric → B Judge
```

B 的 protocol、模型、prompt、schema、aggregation 和 provenance 必须冻结。

---

## 2. Task-level RuVer Human Rubric Memory

检索单元必须是：

```text
task + context + human rubric set
```

而不是：

```text
individual rubric sentence
```

原因是本任务要学习的不是某句 rubric 的文字表达，而是：

> 对相似 AgenticCoding task，人类通常会从哪些评价角度组成一个 rubric set。

### 2.1 MVP memory item

```json
{
  "memory_id": "ruver-agenticcoding:<instance_id>",
  "task_id": "...",
  "task_text": "...",
  "task_summary": "...",
  "task_features": {
    "task_type": [],
    "artifact_type": [],
    "language_or_framework": [],
    "required_operations": [],
    "tool_environment": [],
    "validation_requirements": [],
    "integration_requirement": []
  },
  "human_rubrics": [
    {
      "criterion_id": "SP:...",
      "category": "SP",
      "criterion": "...",
      "gold_label": "success | fail",
      "source_path": "..."
    }
  ],
  "source": "ruverbench",
  "source_version": "...",
  "task_digest": "sha256:...",
  "rubric_digest": "sha256:...",
  "provenance_status": "aligned | incomplete | suspicious | unverifiable"
}
```

`gold_label` 只保留 RuVer 原始信息，不被重新解释为新的 Gold 标注规则。若原始数据无法确认 label 是 observed execution 还是 normative expectation，记录为 `unclear`，并限制其用途为 human evaluation prior。

### 2.2 Memory freeze 要求

Memory freeze 阶段只做三件事：

1. 读取 RuVer task、环境字段、原始 human rubric/checklist 和 labels；
2. 按 task 聚合为一个 memory item；
3. 生成稳定 digest 和来源记录。

不要在 memory freeze 阶段：

- 重新生成 rubric；
- 修改人工 rubric 文本；
- 重写 Gold；
- 按 Judge 结果筛掉案例；
- 将 generated rubric 写回 memory。

---

## 3. MVP Task Representation

第一阶段不让 feature extraction 本身变成新的研究问题。

只要求稳定提取以下高价值字段：

```text
task_type
artifact_type
language_or_framework
required_operations
tool_environment
validation_requirements
integration_requirement
```

### 3.1 推荐值域

`task_type`：

```text
bug_fix
feature_addition
file_operation
repo_understanding
refactor
validation
other
```

`required_operations`：

```text
edit_code
search_repo
run_tests
lint
typecheck
build
manipulate_file
integrate_module
inspect_output
```

### 3.2 特征来源

优先来源：

1. task text / user query；
2. scaffold、tools、environment metadata；
3. artifact contract、expected output、静态 task metadata；
4. 已有 RuVer taxonomy。

每个字段保留来源：

```json
{
  "value": ["run_tests", "typecheck"],
  "source": "task_text | environment | metadata | taxonomy",
  "confidence": "high | medium | low"
}
```

### 3.3 暂时降级为 diagnostic feature

以下字段第一阶段只作为可选诊断信息，不作为 retrieval 强依赖：

```text
requires_global_context
requires_multi_step_execution
success_conditions
requires_external_input
fine_grained task_domain
```

不应为了 feature completeness 延迟 retrieval pilot。

禁止使用以下信息生成 retrieval feature：

- held-out human rubric；
- held-out Gold label；
- Judge prediction；
- 事后根据生成质量修改的标签。

---

## 4. MVP Retrieval

### 4.1 第一版方法

第一版保持简单：

```text
task semantic similarity
+
少量 structured metadata
```

如果已有 embedding 基础设施，则 semantic similarity 作为主信号；structured metadata 只用于 filter、rerank 或 tie-break。

可以使用固定、未经调参的公式：

```text
retrieval_score = semantic_similarity + small_structured_bonus
```

但不为公式本身开展调参实验，也不实现 learning-to-rank。

### 4.2 默认参数

```text
top_k = 5
允许范围 = 5–10
random baseline seed = 固定值
```

Retrieval 必须返回 task context 和整组 human rubrics：

```json
{
  "query_task_id": "...",
  "retrieved_task_id": "...",
  "rank": 1,
  "similarity_score": 0.0,
  "matched_features": [
    "bug_fix",
    "typecheck",
    "multi_file_integration"
  ],
  "human_rubrics": [],
  "excluded_memory_ids": [],
  "selection_method": "semantic | semantic+structured"
}
```

### 4.3 Self-exclusion 与 leakage protection

对每个 held-out task，必须保证：

```text
held_out_task_id 不在 retrieved_task_ids
held_out_task_id 不在 memory_task_ids
held-out rubric 文本不进入 task representation
```

同时排除：

- 同一 task 的别名记录；
- 同一 task 的其它 rubric 视图；
- 旧 analysis 文件中缓存的 held-out rubric；
- 可通过 task_id 间接恢复 held-out rubric 的缓存。

Manifest 和 retrieval result 都要保存排除列表，并由 runner 做 assert。

---

## 5. Retrieval Quality Gate

这是 MVP 的强制停止点：

```text
retrieve
→ retrieval sanity check
→ generation
```

不能在 retrieval 质量未经检查时直接大规模生成 rubric。

### 5.1 Pilot 抽样

第一阶段随机选择约：

```text
20 个 query tasks
```

对每个查看 top-5 retrieval。人工或独立 evaluator 对每个 retrieved task 标记：

```text
0 = irrelevant
1 = partially useful
2 = strongly useful
```

评估对象是“这个 task 的 human rubric set 对当前 query 是否有参考价值”，而不是 task 文本是否相似。

### 5.2 主要指标

```text
useful@5
strongly_useful@5
mean_relevance
```

建议定义：

```text
useful@5 = 至少一个 retrieved item 得分 >= 1
strongly_useful@5 = 至少一个 retrieved item 得分 == 2
```

同时保存：

```text
good retrieval examples
bad retrieval examples
per-query labels
review notes
```

### 5.3 Gate 规则

MVP 不设未经验证的硬阈值，但必须做 go / revise / stop 判断：

- `go`：多数 query 的 top-5 至少包含一个可用案例，且 strong useful 案例不是偶然单点；
- `revise`：task text 相似但 human rubric 参考价值不稳定，先调整 representation/retrieval；
- `stop`：top-5 普遍无关，或 retrieval 结果主要依赖明显错误的 metadata。

如果 retrieval quality gate 未通过，不继续大规模 generation，也不调用 B Judge。

---

## 6. 四组 Rubric Generation 条件

原有 A/B/C 保留，并新增 D。四组条件必须使用同一个 generator、validator、schema、runner 和模型配置。

### A. Task-only

```text
Task + environment
→ Generate rubric
```

用途：测试模型自身 rubric generation baseline。

### B. Random Human Examples

```text
Task + k 个随机 RuVer task + human rubric set
→ Generate rubric
```

使用固定 seed，目的不是追求随机样本最优，而是检验“提供 examples 本身”是否带来收益。

### C. Retrieved Similar Human Examples

```text
Task + top-k similar RuVer task + human rubric set
→ Generate rubric
```

这是 task-specific retrieval 主条件。

### D. Global RuVer Rubric Profile

```text
Task + 固定 RuVer AgenticCoding evaluation profile
→ Generate rubric
```

Global profile 由 training/reference memory 中的 human rubric 离线汇总得到，例如：

```text
RuVer AgenticCoding commonly evaluates:

- outcome correctness
- requirement coverage
- integration with existing system
- tool-policy compliance
- validation/testing
- process completion
- failure handling
- artifact correctness
```

D 不提供 task-specific retrieved examples，用于回答：

> C 的收益来自 task-specific retrieval，还是只需要告诉模型 RuVer 通常关注哪些评价维度？

因此最重要的应用比较是：

```text
C vs D
```

### 6.1 条件公平性

A/B/C/D 除 demonstration 来源外，必须冻结：

```text
generator model/provider
system prompt
prompt template
output schema
temperature/reasoning config
minimal validator
revision limit
task input
held-out split
```

四组条件共享同一执行入口。不同仅通过 manifest/config 表达。

---

## 7. MVP Rubric Generator Schema

第一版不要求每条 criterion 填写所有复杂 metadata。

每条 generated criterion 只要求：

```json
{
  "criterion_id": "gen_001",
  "criterion": "...",
  "rubric_semantic_family": "outcome",
  "evidence_scope": "artifact | runtime | state | mixed",
  "source_basis": [
    "task_requirement",
    "environment_contract",
    "retrieved_human_pattern"
  ],
  "subrequirements": []
}
```

可选字段只在适用时要求：

```text
aggregation_rule
absence_semantics
boundary_notes
anchors
```

### 7.1 `rubric_semantic_family`

它只是工程上的 semantic category，不是 human intent Gold。可选值：

```text
outcome
requirement_coverage
integration
tool_policy
validation
process_completion
failure_handling
artifact_quality
style_or_communication
safety_or_constraint
other
```

### 7.2 必须触发的局部规则

- compound criterion → 必须有 `subrequirements` 和 `aggregation_rule`；
- negative / absence criterion → 必须有 `absence_semantics`；
- vague term → 必须有 `boundary_notes` 或 `anchors`；
- 普通 atomic criterion → 不机械补齐上述字段。

### 7.3 Generator 的行为约束

Generator 应先总结适用于当前 task 的评价维度，再生成具体 criterion，但不应机械复制 retrieved rubric。

每条 criterion 应至少能追溯到：

```text
当前 task requirement
或 environment/tool contract
或多个 retrieved human rubric 中与当前 task 相适用的 pattern
```

禁止仅凭模型偏好增加：

```text
代码应该优雅
回答应该专业
应该使用某种特定工具
```

除非当前 task、environment 或 RuVer pattern 明确支持。

---

## 8. MVP Rubric Validator

第一版 Validator 只检查最容易造成实际损害的五类问题：

```text
1. duplicate criterion
2. unsupported / irrelevant criterion
3. compound criterion without explicit aggregation
4. negative / absence criterion without absence semantics
5. obvious vague term without boundary or anchor
```

### 8.1 执行方式

```text
generate
→ validate
→ 最多 revise 一次
→ accept / drop
```

不做无限 self-refinement。

如果需要语义检查，第一版只回答：

```text
这个 criterion 是否适用于当前 task？
```

不回答：

```text
criterion 是否满足
Gold 应该是什么
Agent 表现好坏
```

### 8.2 Validator 输出

```json
{
  "task_id": "...",
  "condition": "...",
  "valid": true,
  "issues": [
    {
      "severity": "error | warning",
      "type": "vague_without_anchor",
      "criterion_id": "gen_002",
      "message": "..."
    }
  ],
  "recommended_action": "accept | revise | drop",
  "revision_count": 0
}
```

---

## 9. Held-out Reconstruction Evaluation

### 9.1 Protocol

对每个 held-out RuVer task：

1. 隐藏自己的原始 human rubric；
2. 从 retrieval memory 中排除自己及其 alias/duplicate；
3. 使用相同 task/environment 表示；
4. 分别生成 A/B/C/D rubric；
5. 通过同一个 minimal validator；
6. 先进行人工/reference alignment inspection；
7. 只有值得继续时，最后调用固定 B Judge 做 downstream evaluation。

### 9.2 Pilot 规模

第一阶段：

```text
10–20 held-out tasks
```

但顺序不是一开始就完整跑完所有 Judge：

```text
先 retrieval quality gate
→ 再生成 A/C/D
→ 再做人工生成质量检查
→ 再决定是否补 B random baseline
→ 最后才做 B Judge downstream evaluation
```

---

## 10. N:M Human/Generated Alignment

不能假设：

```text
1 human criterion = 1 generated criterion
```

允许：

```text
1 human → N generated
N human → 1 generated
```

例如：

```text
Human H1: Use real tool outputs correctly.
Generated G1: Read actual tool outputs.
Generated G2: Use relevant tool outputs to guide subsequent actions.
```

必须建立 semantic alignment 后才能进行 criterion-level correspondence analysis：

```json
{
  "human_criterion_ids": ["H1"],
  "generated_criterion_ids": ["G1", "G2"],
  "relation": "decomposition",
  "semantic_match": true,
  "aggregation": "ALL",
  "confidence": "high"
}
```

支持的关系：

```text
one_to_one
decomposition
merge
partial_overlap
unmatched_human
extra_generated
```

### 10.1 Gold 继承禁令

Generated rubric 没有天然 Gold。

不能因为 `H1=True` 就直接给 `G1=True`、`G2=True`。对于 decomposition 或 merge：

- 若语义和聚合关系可可靠确定，记录 correspondence 分析；
- 若无法可靠映射，标记 `unmapped`；
- 不人为创建 pseudo-Gold。

---

## 11. 第一阶段核心评价指标

第一阶段只保留少量真正影响工程决策的指标。

### 11.1 Human concern recall

held-out human rubric 中主要评价 concern 被 generated rubric 覆盖的比例。

不要求文本相同，优先通过 `rubric_semantic_family` + 人工/语义匹配判断。

### 11.2 Unsupported / irrelevant extra rate

```text
unsupported_extra_rate
= unsupported or irrelevant generated criteria
  / generated criteria
```

判断时必须考虑当前 task 和 environment；不能简单地因为 human rubric 中未出现就判 unsupported。

### 11.3 Granularity 诊断

只记录：

```text
human criterion count
generated criterion count
compound ratio
```

并人工抽查：

```text
明显过粗
明显过细
合理
```

第一阶段不构建复杂 granularity score。

### 11.4 可选下游指标

在通过人工/reference alignment inspection 后，才使用固定 B Judge 比较：

```text
human rubric
vs
A generated
vs
B generated
vs
C generated
vs
D generated
```

重点观察：

```text
Gold agreement
Gold-positive recall
FN / FP
repeat stability
```

只有语义 alignment 清楚的 criterion 才进入 criterion-level comparison。`extra_generated`、`missed_human`、`unmapped` 单独报告。

---

## 12. 实施阶段（MVP）

### Phase 1：Memory + Retrieval

实现/复用：

```text
task-level human rubric memory
leakage-safe retrieval
```

先做：

```text
20 query tasks × top-5 retrieval sanity check
```

验收：

- retrieval top-5 人工看来确实包含可用案例；
- self-exclusion assert 生效；
- retrieval 结果可重放；
- 未通过 gate 时不会启动大规模 generation。

### Phase 2：A/C/D Generation Pilot

先跑：

```text
A task-only
C retrieved human examples
D global RuVer profile
```

在 10–20 held-out tasks 上生成 rubric，先不跑 Random baseline，也先不调用 B Judge。

验收：

- C 是否比 A 有实际 coverage 改善；
- C 是否比 D 有额外收益；
- C/D 是否增加 unsupported extra；
- rubric 粒度是否明显偏离 human rubric。

若 C/D 都没有肉眼或指标上的实际改善，停止，不继续消耗 Judge 成本。

### Phase 3：补 B Random Baseline + Minimal Validator

只有方向值得继续时，补齐：

```text
B random human examples
minimal validator
one-pass revision
```

完成四条件公平比较。

### Phase 4：N:M Semantic Alignment

实现并人工抽查：

```text
matched
one_to_one
decomposition
merge
partial_overlap
extra
missed
unmapped
```

### Phase 5：Frozen B Judge Downstream Evaluation

最后才运行：

```text
human/generated rubric
→ existing B Judge
```

在代表性 subset 做 3 repeats，比较 Gold agreement 和稳定性。不修改 B protocol，不把 generated rubric 写回 memory。

---

## 13. Shared Runner 与 Manifest

禁止创建：

```text
run_task_only.py
run_random.py
run_retrieval.py
run_rubric_v2.py
```

应扩展现有共享 meta-eval/experiment 入口，通过配置表达条件：

```text
--mode rubric_generation
--condition task_only | random_human_rubric | retrieved_human_rubric | global_profile
--dataset ruver_agenticcoding
--heldout-split ...
--top-k 5
--seed ...
--out ...
```

### 13.1 Manifest 最小字段

```json
{
  "experiment_id": "rubric-generation-pilot-20260901",
  "hypothesis": "task-specific human rubric retrieval has practical value beyond task-only and global profile baselines",
  "dataset": {
    "id": "ruverbench.agenticcoding",
    "version": "...",
    "task_source": "...",
    "trajectory_source": "...",
    "gold_source": "..."
  },
  "held_out_task_ids": [],
  "memory_task_ids": [],
  "conditions": [
    "task_only",
    "random_human_rubric",
    "retrieved_human_rubric",
    "global_profile"
  ],
  "retrieval": {
    "method": "semantic | semantic+structured",
    "top_k": 5,
    "seed": 0,
    "excluded_task_ids": []
  },
  "global_profile": {
    "source_memory_task_ids": [],
    "profile_digest": "sha256:..."
  },
  "generator": {
    "model": "...",
    "provider": "...",
    "temperature": 0,
    "prompt_digest": "sha256:...",
    "schema_version": "agenteval.generated_rubric.v1"
  },
  "validator": {
    "version": "mvp",
    "prompt_digest": "sha256:...",
    "max_revisions": 1
  },
  "downstream_judge": {
    "protocol": "B_joint_multi_rubric",
    "protocol_version": "agent-eval.abcd.frozen.v1/B",
    "model": "...",
    "config_digest": "sha256:..."
  },
  "input_digests": {
    "dataset": "sha256:...",
    "trajectories": "sha256:...",
    "gold": "sha256:...",
    "memory": "sha256:..."
  },
  "runner_commit": "...",
  "status": "design | pilot | complete | invalid"
}
```

特别注意：global profile 必须只由 training/reference memory 生成，不能使用 held-out task 的 human rubric。profile 生成后必须 freeze、hash，并写入 manifest。

---

## 14. 推荐产物

通过 pilot 后，建议生成：

```text
rubric_memory.jsonl
task_features.jsonl
retrieval_results.jsonl
retrieval_quality_review.jsonl
global_rubric_profile.json
generated_rubrics_task_only.jsonl
generated_rubrics_random_human_rubric.jsonl
generated_rubrics_retrieved_human_rubric.jsonl
generated_rubrics_global_profile.jsonl
rubric_validation.jsonl
intent_alignment.jsonl
judge_results_human.jsonl
judge_results_generated.jsonl
rubric_generation_metrics.json
retrieval_ablation.json
stability_metrics.json
experiment_manifest.json
RUBRIC_GENERATION_REPORT.md
```

这些是计划产物，不代表当前已经存在，也不应在本阶段伪造结果。

---

## 15. 决策规则与停止条件

最终目标是选择最简单且足够好的生产方案，而不是证明 RAG 必须获胜。

### 15.1 需要回答的最小问题

```text
1. Retrieval top-5 是否真的包含有用的人类 rubric examples？
2. C 是否比 A 生成更好的 rubric？
3. C 是否比 D 的 global profile 有额外收益？
4. C 是否没有明显增加 unsupported/irrelevant rubric？
5. Generated rubric 的粒度是否仍接近 human rubric？
```

### 15.2 结果解释

- 若 `D ≈ C`：优先考虑固定 global RuVer rubric profile，而不是长期维护 retrieval；
- 若 `A ≈ C ≈ D`：说明 generator 本身已经足够，human rubric retrieval 没有明显应用收益；
- 若 `C > D` 且差异稳定、extra rate 和 granularity 不恶化：才保留 task-specific retrieval；
- 若 retrieval quality gate 不通过：先修 retrieval，不进入大规模 generation；
- 若 generated rubric 产生大量 unsupported、vague 或 absence ambiguity：不进入生产。

这里的 `≈` 和 `>` 必须由固定 manifest 下的实际指标、人工抽查和必要的区间共同判断，不能根据预期结论修改样本或指标。

### 15.3 生产候选不预设

实验可能得到以下任一生产方案：

```text
Task-only
Task + static RuVer rubric profile
Task + retrieved similar human rubric examples
```

在结果出来之前，不预设 retrieval 必须成为生产方案。

---

## 16. 本阶段完成定义

本阶段仅完成方案收敛，不代表实现完成。

完成标准：

- 已明确 MVP 的 task representation 字段；
- 已明确 task-level memory 结构；
- 已加入 retrieval quality gate；
- 已加入 global profile baseline；
- 已明确四组公平条件；
- 已缩小 generator/validator schema；
- 已保留 held-out leakage protection；
- 已明确 N:M alignment 和禁止 Gold 继承；
- 已将 B Judge downstream evaluation 后置；
- 已明确 shared runner、manifest、产物和停止条件。

下一阶段才开始 Phase 1：冻结 memory 与 retrieval sanity check，不直接进行大规模 rubric generation 或 B Judge 调用。
