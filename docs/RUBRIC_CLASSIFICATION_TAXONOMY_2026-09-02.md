# Rubric classification taxonomy: grounding × scope × applicability × evidence_source × atomicity × capability

日期：2026-09-02  
状态：Active 分类字段定义；Applicability 已废弃。历史 applicability 输出保留，但不进入当前 active rubric 统计。

## 1. 分类要回答的八个不同问题

Human/Benchmark/Task、process/outcome/policy/artifact、hard/soft、objective/subjective 与 capability 是平行的分类轴；新增字段不替代、不合并、也不重命名原有分类。

```text
grounding       = 这条 rubric 从哪个层级来
scope           = 评什么
applicability   = 什么时候适用
evidence_source = 从哪里取证
atomicity       = 这条 rubric 是否是单一判断
hardness        = 判定边界是硬还是软
judgment_type   = 判定是客观还是主观
capability      = 这条 rubric 评价哪种能力
```

原有 grounding 轴：

```text
grounding.primary:
  human_general
  benchmark_specific
  task_specific

grounding.secondary: []
```

新增 scope 轴：

```text
scope.primary:
  process
  outcome
  policy
  artifact

scope.secondary: []
```

这些轴必须并列保存，不能互相替代。例如：

```text
grounding.primary = task_specific
scope.primary = artifact
```

表示该 criterion 来源于当前 task，并评价最终 artifact。

## 2. scope：评什么（新增 scope_type 轴）

每条 criterion 设置一个 `scope.primary`，必要时设置 `scope.secondary`。

允许值：

### process

评价 Agent 如何做事：

```text
是否先读文件再修改
是否先探索再行动
是否正确处理工具错误
是否恢复失败
是否运行验证步骤
```

### outcome

评价最终任务结果是否正确：

```text
功能是否实现
答案是否正确
任务是否完成
结果是否满足成功条件
```

### policy

评价是否遵守规则或约束：

```text
不能用 Bash 修改文件
必须遵守 ToolSchema
必须遵守安全规则
不能执行禁止的操作
```

### artifact

评价最终产物本身的质量或属性：

```text
Excel 公式是否正确
PPT 格式是否符合要求
文档结构是否完整
代码文件内容是否正确
```

一个 criterion 如果同时评价多个 scope，不强行压成单一标签：

```json
{
  "scope": {
    "primary": "artifact",
    "secondary": ["outcome"]
  }
}
```

但如果多个部分可以独立判断，优先拆成 atomic criteria，而不是滥用 secondary scope。

## 3. 原有 grounding：Human 通用 / Benchmark / Task

该轴继续保留，用于回答 rubric 的来源层级：

```text
grounding.primary:
  human_general
  benchmark_specific
  task_specific

grounding.secondary: []
```

它与 `scope` 正交：

```text
grounding.primary = task_specific
scope.primary = artifact
```

表示当前 task 明确要求评价某个 artifact 属性。

```text
grounding.primary = benchmark_specific
scope.primary = policy
```

表示 benchmark 统一规范要求评价某项规则遵守情况。

## 4. applicability：已废弃，不进入当前 active taxonomy

本字段曾用于区分 `always / conditional / task_specific`，但人工抽查后确认它对当前分析帮助有限，现不再作为 active 分类轴。历史结果只作 provenance 保留，不用于后续 rubric 统计、生成条件比较或 capability 分析。

允许值：

### always

只要进入该 benchmark/environment，几乎始终适用：

```text
明确的安全规则
全局系统约束
benchmark 固定格式要求
```

### conditional

只有触发条件成立时才适用：

```text
如果进行了 broad search，则应该使用 Explore
如果发生 tool error，则应该进行恢复
如果任务要求外部输入，则必须先获取该输入
```

没有触发条件时，不能将该 criterion 硬判为 False。

### task_specific

只对当前具体 task 成立：

```text
必须生成 amortization schedule
必须实现 W_Type 展示
必须创建三个指定 worksheet
```

## 5. evidence_source：从哪里取证

允许值：

### trajectory

主要从 runtrace、tool calls、messages 中判断：

```text
是否调用 Explore
是否运行测试
是否先读取文件
是否提前停止
是否恢复失败
```

### artifact

主要从最终文件、代码、文档中判断：

```text
Excel 公式是否正确
代码是否存在
PPT 是否包含指定内容
文档结构是否完整
```

### state

需要查看环境最终状态：

```text
数据库状态
文件系统状态
容器状态
测试状态
编译状态
```

### mixed

必须结合两种或以上信息：

```text
正确修改代码并运行验证
```

需要同时查看：

```text
artifact：代码是否被正确修改
trajectory/state：是否真的运行了 test，test 状态是什么
```

`evidence_source` 的作用是防止生成：

```text
理论上合理、但当前 Judge 没有证据源可以判断
```

## 6. atomicity：是否是单一判断

允许值：

### atomic

基本只有一个独立的 Yes/No 判断：

```text
是否运行了 typecheck？
是否生成 .xlsx 文件？
是否存在 Prepaid Summary worksheet？
```

### compound

包含多个子要求：

```text
正确实现功能、运行测试并在最终回答中说明修改。
```

compound 不是绝对禁止，但必须同时提供：

```json
{
  "atomicity": "compound",
  "subrequirements": [
    "功能实现正确",
    "运行测试",
    "最终回答说明修改"
  ],
  "aggregation_rule": "ALL"
}
```

允许的 `aggregation_rule`：

```text
ALL
ANY
weighted
not_applicable
```

## 7. capability：评价哪种能力

capability 是独立的能力轴，不能被 `scope` 或 `grounding` 替代。

每条 criterion 保存：

```text
primary_capability       一个
secondary_capabilities   零到两个
```

例如：

```text
scope.primary = artifact
capability.primary = formula_design
```

表示这条 rubric 评价最终 artifact 中的公式设计能力。

```text
scope.primary = process
capability.primary = failure_recovery
```

表示这条 rubric 评价 Agent 在执行过程中的失败恢复能力。

capability taxonomy 只是跨 rubric 比较的分析坐标，不是：

```text
Agent capability score
Gold satisfaction label
Judge prediction
```

当前 GDPval capability 示例：

```text
artifact_creation
spreadsheet_structure
formula_design
financial_calculation
source_data_extraction
reconciliation
monthly_schedule_reasoning
account_classification
file_format_compliance
artifact_validation
numeric_precision
cross_sheet_integration
presentation_formatting
comment_annotation
completion_reporting
```

## 7. 与其它属性的关系

本轮暂时保留以下两个独立字段：

```text
hardness:
  hard | soft

judgment_type:
  objective | subjective
```

它们与新字段的关系是：

```text
scope          = 评什么
applicability  = 什么时候适用
 evidence_source = 从哪里取证
atomicity      = 是否一个判断
hardness       = 判定边界是否明确
judgment_type  = 评审者是否可能合理分歧
capability     = 评价哪种能力
```

不得混淆：

```text
process != trajectory
outcome != artifact
conditional != soft
compound != subjective
artifact != always
```

例如：

```text
“如果发生 tool error，则必须进行恢复”
```

应当是：

```text
scope = process
applicability = conditional
evidence_source = trajectory
atomicity = atomic
```

而：

```text
“Excel Summary totals must be linked to the detailed tabs by formulas”
```

应当是：

```text
scope = artifact
applicability = task_specific
evidence_source = artifact
atomicity = atomic
```

## 8. 推荐 schema

```json
{
  "criterion_id": "...",
  "criterion": "...",
  "classification": {
    "grounding": {
      "primary": "task_specific",
      "secondary": []
    },
    "scope": {
      "primary": "artifact",
      "secondary": ["outcome"]
    },
    "applicability": "task_specific",
    "evidence_source": "artifact",
    "atomicity": "atomic",
    "subrequirements": [],
    "aggregation_rule": "not_applicable",
    "hardness": "hard",
    "judgment_type": "objective",
    "primary_capability": "formula_design",
    "secondary_capabilities": ["cross_sheet_integration"],
    "confidence": "high",
    "basis": "..."
  }
}
```

字段约束：

```text
grounding.primary       必填
grounding.secondary     默认 []
scope.primary           必填
scope.secondary         默认 []
applicability       必填
evidence_source     必填
atomicity           必填
subrequirements     compound 时必填，atomic 时默认 []
aggregation_rule    compound 时必填，atomic 时为 not_applicable
hardness            必填
judgment_type       必填
primary_capability  必填
secondary_capabilities 默认 []
```

## 9. 最重要的用途

### 8.1 识别 conditional rubric 被误用

这是 C retrieval 的关键风险：

```text
历史 task 中 conditional 的 rubric
```

可能被 Generator 错当成：

```text
当前 task 的 mandatory rubric
```

因此生成和分析时必须同时检查：

```text
retrieved criterion 的 applicability
当前 task 是否满足触发条件
```

### 8.2 区分 task-specific 与通用 benchmark 规则

```text
scope = artifact/outcome/process/policy
```

描述评价对象；

```text
applicability = always/conditional/task_specific
```

描述适用条件。

这两个维度不能再用一个 scope 字段混合表达。

### 8.3 检查 Judge 是否有证据可用

```text
trajectory criterion → 需要 trajectory
artifact criterion   → 需要 artifact
state criterion      → 需要 state
mixed criterion      → 需要多种证据
```

### 8.4 分析 compound rubric 风险

compound criterion 必须显式保存：

```text
subrequirements
aggregation_rule
```

否则不能进入严格的 criterion-level comparison。

## 10. 本轮边界

本文件只定义和冻结分类字段，不改变：

```text
GDPval task
Gold rubric
A/C/D generated rubric
B Judge
既定实验条件
既定实验顺序
```

后续如执行分类，只将这套字段应用到已有的 Gold/A/C/D rubric 输出，并单独生成 classification artifacts。
