# 60-case Gold 数据集重构方案

日期：2026-08-31  
状态：proposal / not yet executed

## 1. 先明确当前数据集的问题

当前 60 条并不是同一种统计单位：

```text
HealthBench              20 个 prompt/task
RuVerBench DeepResearch   20 个 rubric point（来自若干 task）
RuVerBench AgenticCoding  20 个 checklist check（来自若干 trajectory/task）
```

而且当前为了适配 Judge API，很多样本被投影为：

```text
request + 一个 rubric + 一个 binary label
```

这个投影适合做最小 baseline，但不能作为唯一正式数据结构，原因是：

1. HealthBench 原始 task 可以有多个 rubric point；
2. DeepResearch 原始 response/task 也包含多个 coverage point；
3. AgenticCoding 原始 trajectory/task 包含多个类别和 checks；
4. 同一个 task 的多个 rubric point 不是独立同分布样本；
5. “60 个 case”当前混合了 task-level、rubric-level、check-level 三种 unit；
6. 机械拆分会丢失 task-level context，也无法公平测试 planner/router/multi-question judge。

因此当前问题不是简单增加样本数量，而是先恢复数据的层级和统计单位。

## 2. 推荐的数据集不是一个表，而是三层结构

### Layer A：Raw source（只读）

保留外部 benchmark 原始文件，不改写：

- 原始 task/request；
- 原始 response/trajectory；
- 原始 rubric/checklist；
- 原始 label/consensus；
- 原始 benchmark metadata。

当前来源至少包括：

```text
HealthBench 原始 prompt / rubric / consensus
RuVerBench deepresearch_dataset / labels / responses / taxonomy
RuVerBench agenticcoding_dataset / labels / trajectories
```

### Layer B：Canonical task record（研究主数据）

一条记录代表一个原始 task 或 trajectory，不是一个 rubric point。

建议字段：

```json
{
  "task_id": "source-stable-id",
  "benchmark": "healthbench|ruverbench_deepresearch|ruverbench_agenticcoding",
  "source_task_ref": "原始文件 + 原始 id",
  "request": "原始用户问题",
  "response": "完整回答（如有）",
  "trajectory_ref": "完整轨迹引用（如有）",
  "artifact_ref": "产物引用（如有）",
  "rubric_items": ["criterion_id", "criterion_id"],
  "task_metadata": {},
  "gold_status": "gold|candidate|unavailable",
  "gold_aggregation": "source_defined|criterion_only|not_defined",
  "provenance": {}
}
```

这一层用于：

- 恢复 task-level context；
- 运行 multi-rubric；
- 让 planner/router 看到完整 task；
- 防止同一个 task 的 rubric point 被误当成完全独立样本。

### Layer C：Judge view（实验投影）

同一个 canonical task 可以生成不同的 judge view，但不能复制或修改 Gold：

```text
M0 mechanical_single_rubric
M1 gold_multi_rubric
M2 gold_multi_rubric_dynamic_planner
M3 gold_multi_rubric_skill_router
```

建议字段：

```json
{
  "view_id": "task-001__M0",
  "task_id": "task-001",
  "condition": "M0",
  "rubric_context": {},
  "selected_criterion_ids": ["c1"],
  "judge_input_ref": {},
  "gold_refs": ["c1"],
  "aggregation_rule": "source_defined|weighted_mean|not_applicable",
  "input_digest": "sha256"
}
```

关键原则：

> M0/M1/M2/M3 是不同输入视图，不是四份不同 Gold 数据。

## 3. Gold 标签必须保留两个层级

### 3.1 Criterion-level Gold

这是最可靠、最普遍可用的标签：

```text
某个 response/trajectory 是否满足某个具体 criterion/check
```

DeepResearch 和 AgenticCoding 当前已有的 `point_id/check_id + true/false` 应保留在这一层。

HealthBench 如果原始 consensus 只提供 rubric 层或 reviewer 结果，也必须保留其原始语义，不要直接强制转成二元 criterion label。

### 3.2 Task-level Gold

只有外部 benchmark 明确定义了 task-level 聚合规则时才生成：

```text
source_defined_task_label
```

如果没有官方 task-level label，就记录：

```text
"gold_aggregation": "criterion_only"
```

不能用“所有 rubric 都通过”“平均分超过 0.5”等自行发明的规则作为 headline Gold。

## 4. 60-case 主集如何处理

不建议直接丢掉现有 60 条，也不建议继续把它们当作 60 个同质 task。

建立两个并行统计视图：

### View 1：Legacy 60-instance headline

保留现有 60 个 Judge instance，保证历史结果可复现：

```text
HealthBench 20
DeepResearch 20 rubric points
AgenticCoding 20 checks
```

用途：

- 对比旧实验结果；
- 评估最小改动是否在同一输入上提分；
- 作为 legacy adapter baseline。

名称应改为：

```text
legacy_60_judge_instances
```

不要再称作“60 个 task”。

### View 2：Task-grouped Gold set

将上述 instance 按原始 task/trajectory 重新分组：

```text
一个 task
→ 完整 request/response/trajectory
→ 全部可追溯 rubric/checks
→ criterion-level Gold
```

用途：

- 测试黄金多 rubric；
- 测试 planner；
- 测试 router；
- 计算 task-cluster bootstrap 和 per-criterion 结果。

同一个 task 下多个 criterion 必须按 task cluster 统计置信区间，不能把每个 criterion 当成完全独立样本。

## 5. 新数据集的抽样原则

第一阶段不要盲目从 60 扩成一个随机大集合。先做结构化扩充。

### 5.1 三个 benchmark 的 task 数量

推荐先从每个 benchmark 选择：

```text
10 个 task × 3 benchmark = 30 个 canonical task
```

如果材料和成本允许，再扩展到：

```text
20 个 task × 3 benchmark = 60 个 canonical task
```

但每个 task 保留全部可用 rubric/check，不再只抽一个 point。这样最终 criterion-level judgment 数量可以大于 60，但 task-level 样本分母仍然清楚。

### 5.2 分层维度

每个 benchmark 内至少按以下维度分层：

1. gold label：positive / negative，尽量接近平衡；
2. rubric/check category；
3. rubric count：single / 2-5 / 6+；
4. task complexity：simple / multi-step / cross-constraint；
5. evidence type：answer-only / reference-required / trajectory-required / mixed；
6. ambiguity：clear / partial / ambiguous（仅在原数据有依据时）；
7. source task family/domain；
8. response/trajectory length。

不要只按 benchmark 数量平均，因为 benchmark 内部类别仍可能极度集中。

### 5.3 多 rubric 的覆盖要求

正式测试 planner/router 的数据集中，至少应包含：

```text
single-criterion task
multi-criterion task
criteria with different semantic types
criteria with different evidence needs
positive and negative criteria in the same task
```

如果一个 task 只有一个可用 criterion，它可以进入 M0，但不能作为证明 multi-rubric 提分的样本。

## 6. M0/M1/M2/M3 的数据契约

### M0：机械单 rubric

```text
完整 task context（可保留）
+ 一个 criterion
+ 当前生产 Judge 输入格式
```

M0 的“单 rubric”指判定问题数量为一个，不代表必须丢掉 request 或完整 trajectory。

### M1：黄金多 rubric

```text
完整 task context
+ task 原始/黄金 rubric 集合
+ 每个 criterion 独立 question judgment
+ 明确 aggregation
```

M1 的 Gold 仍然是 criterion-level Gold；如果官方没有 task-level Gold，只报告 criterion-level accuracy 和明确声明的聚合分析，不伪造 task label。

### M2：动态 rubric planner

```text
黄金 rubric 作为边界
→ planner 选择/排序/补充 question
→ 不得删除 Gold criterion
→ 不得改变 criterion 的 Gold label
```

要记录：

- planner 输入；
- selected criterion；
- generated question；
- question-to-gold mapping；
- 未覆盖 criterion。

### M3：skill router + multi-question judge

```text
criterion
→ skill/evidence route
→ criterion judgment
→ source-defined/explicit aggregation
```

M3 不是新的 Gold，而是同一 canonical task 的另一种执行方式。

## 7. 当前最小可执行步骤

### Step 1：只读盘点

建立一张 mapping：

```text
legacy case
→ source task id
→ all rubric/check ids
→ gold label source
→ category
→ response/trajectory ref
```

### Step 2：生成 canonical task index

不运行 Judge，不运行 Harbor，不改源数据。只生成：

```text
canonical_tasks.jsonl
criterion_gold.jsonl
legacy_instance_views.jsonl
```

### Step 3：先选有真实多 rubric 的 task

优先从 HealthBench 和 AgenticCoding 中选择 rubric/check 数量大于 1、且 Gold 可追溯的 task，再构造 M0/M1。

DeepResearch 先检查原始任务下多个 coverage points 是否完整可用；如果可用，也按 task 分组，否则只作为 criterion-level 对照。

### Step 4：冻结数据版本

生成：

```text
dataset_manifest.json
source_digests.json
sampling_manifest.json
```

之后所有 Judge 条件使用同一版本，不重新随机抽样。

### Step 5：再运行最小实验

只先跑：

```text
M0 vs M1
```

先不跑 dynamic planner 和 skill router。只有 M1 有可重复提分，才继续 M2/M3。

## 8. 统计报告规则

必须同时报告三种分母：

```text
instance-level：criterion/check 判定准确率
cluster-level：按 task 聚合后的准确率
benchmark-level：三个 benchmark 的 macro average
```

同时报告：

- 总体 accuracy；
- balanced accuracy；
- positive F1；
- Gold MAE（仅在 Gold 语义可比时）；
- per-benchmark；
- per-category；
- 单 rubric vs 多 rubric；
- paired transition；
- task-cluster bootstrap CI。

不能只报告把所有 criterion 展平后的一个 accuracy，因为多 rubric task 会被重复加权。

## 9. 哪些数据不能混入主 accuracy 集

以下数据保留为辅助 fixture，不和 60-case 主集混合：

- closed-loop smoke；
- failure-handling 三 case factorial；
- judge calibration 专用 Gold；
- 只有人工候选标签、尚未 adjudicate 的 HealthBench case；
- 无法确定原始 task/criterion provenance 的历史结果。

## 10. 最终建议

当前不要先“再随机抽 60 条”。正确顺序是：

```text
原始数据恢复
→ task/criterion 分层
→ 保留完整多 rubric
→ 建立 legacy adapter view
→ 建立 grouped canonical view
→ 冻结 manifest
→ M0 vs M1
→ 只有提分后才测试 planner/router
```

一句话：

> 现在要修的不是 Judge prompt，而是 Gold 数据的统计单位和 rubric 拓扑；单 rubric 作为历史 baseline 保留，多 rubric 作为真实系统能力的可检验条件加入。
