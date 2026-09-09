# Capability Alignment Role：Task/Trace/Rubric 与 Agent Capability 的多对多对齐方案

日期：2026-09-02  
状态：MVP 设计修订；先完成单 task capability coverage alignment pilot，不修改 Gold、不修改 B Judge、不新增 Judge protocol。

## 1. 目的

新增一个独立的分析角色，用来回答：

> Gold rubric、A/C/D generated rubric 分别在评价哪些 Agent capability？这些 capability 有多少重合、遗漏和额外扩张？

本角色的目标不是再次判断 agent 是否完成 rubric，也不是预测 Gold label，而是把：

```text
task + runtrace + rubric criterion
```

映射到一组可复用的 Agent capability，并比较不同 rubric set 的 capability coverage。

## 2. 角色边界

角色名称：`CapabilityAlignmentAnalyst`

它不是：

- B Judge；
- Rubric Validator；
- Gold adjudicator；
- evidence collector；
- adaptive router；
- agent capability scorer。

它只做：

```text
识别 criterion 涉及的 capability
建立 criterion ↔ capability 多对多关系
区分 task-required / trace-observed / rubric-evaluated capability
比较 Gold 与 A/C/D 的 capability overlap
```

禁止输出：

```text
criterion satisfied / not satisfied
Gold 是否正确
Judge 是否正确
新的 Gold label
```

## 3. 输入

每个分析实例包含：

```json
{
  "task": "...",
  "trace": "...",
  "rubric_set": "gold|A|C|D",
  "rubric_criteria": []
}
```

其中：

- `task`：当前 AgenticCoding task；
- `trace`：该 task 的冻结 runtrace；
- `rubric_criteria`：Gold 或某一 generated rubric set；
- 不提供 Gold label、B Judge prediction、accuracy、flip 信息。

为了做跨 rubric set 对比，同一个 task 的 Gold/A/C/D 都使用同一 task 和同一 trace。

## 4. Capability 表示

第一版不建立复杂的 latent capability ontology。使用可读、可审计的 capability atom。

建议初始 capability family：

```text
repo_navigation
context_inspection
requirement_parsing
planning
scope_control
file_read_before_write
code_editing
multi_file_integration
type_system_reasoning
implementation_design
tool_selection
tool_schema_compliance
tool_result_use
parallel_action_coordination
task_state_tracking
test_execution
lint_build_validation
artifact_verification
failure_recovery
completion_reporting
communication_formatting
safety_constraint_following
dependency_management
```

`capability_family` 是分析标签，不是 human capability Gold，也不是模型能力测量。

如果无法映射，使用：

```text
other
unknown
```

不要为了消除 `unknown` 反复扩展 taxonomy。

## 5. 三种 capability 关系必须分开

同一 capability 要记录不同来源，不能混为一谈。

### 5.1 task_required_capabilities

由 task 明确要求或完成任务必需推断出的 capability。

例如：

```text
实现 W_Type 可读显示
→ type_system_reasoning
→ code_editing
→ implementation_design
```

### 5.2 trace_observed_capabilities

runtrace 中实际可观察到的行为 capability。

例如：

```text
读取 W_Type 定义
→ context_inspection
→ repo_navigation
```

注意：这里记录 observed behavior，不判断该行为是否满足 rubric，也不使用 Gold。

### 5.3 rubric_evaluated_capabilities

某条 rubric criterion 想评价的 capability。

例如：

```text
“修改前先检查相关文件”
→ file_read_before_write
→ context_inspection
```

本轮核心比较对象是：

```text
Gold rubric evaluated capabilities
vs
A/C/D rubric evaluated capabilities
```

## 6. 多对多映射 schema

每个 criterion 允许映射到多个 capability；同一 capability 也允许被多个 criterion 评价。

```json
{
  "task_id": "...",
  "rubric_set": "gold|A|C|D",
  "criterion_id": "...",
  "criterion_text": "...",
  "capability_links": [
    {
      "capability_id": "type_system_reasoning",
      "role": "primary|supporting",
      "relation": "evaluates|requires|observes",
      "evidence_basis": ["task", "trace", "rubric"],
      "applicability": "applicable|uncertain|not_applicable",
      "confidence": "high|medium|low",
      "reason": "..."
    }
  ],
  "criterion_scope": "task_outcome|agent_process|tool_policy|validation|communication|safety|other"
}
```

另生成 task-level capability set：

```json
{
  "task_id": "...",
  "rubric_set": "gold|A|C|D",
  "task_required": [],
  "trace_observed": [],
  "rubric_evaluated": [],
  "unobservable_evaluated": [],
  "uncertain": []
}
```

## 7. 评估流程

```text
冻结 task + trace
        ↓
分别输入 Gold/A/C/D rubric
        ↓
CapabilityAlignmentAnalyst
        ↓
criterion ↔ capability N:M links
        ↓
按 task 聚合 capability set
        ↓
计算 overlap / missed / extra / observability
```

建议先对现有 `agents-spy-type-annotations` 做单 task pilot，确认 schema 能表达 C/D badcase，再扩展到已有 10-task generate pilot。

## 8. 首轮 pilot 的三个核心集合

对同一个 task，先冻结三个集合：

```text
T = task-required capabilities
O = trace-observed capabilities
R_H, R_A, R_C, R_D = each rubric set's primary capabilities
```

本阶段不把 capability mapping 当成 Agent capability score。

## 9. 核心指标

### 8.1 Capability overlap（主指标）

对一个 task，设：

```text
G = Gold rubric evaluated capability set
X = A/C/D generated rubric evaluated capability set
```

计算：

```text
intersection = |G ∩ X|
Gold coverage = |G ∩ X| / |G|
Generated precision = |G ∩ X| / |X|
Jaccard = |G ∩ X| / |G ∪ X|
```

主报告使用：

```text
Gold capability coverage
Jaccard overlap
```

### 8.2 Weighted overlap

为 capability link 设置权重：

```text
primary = 1.0
supporting = 0.5
```

避免一个 generated compound criterion 映射很多 supporting capability 后不合理地抬高 overlap。

### 8.3 Missing capability

```text
Gold capability - Generated capability
```

表示 generated rubric 没有评价 Gold rubric 评价的 capability。

### 8.4 Extra capability

```text
Generated capability - Gold capability
```

但 extra 不等于错误。还要分：

```text
extra_task_supported
extra_trace_observable
extra_human_pattern_supported
extra_unjustified
```

### 8.5 Capability observability

对 generated rubric 评价的 capability，统计：

```text
trace_observed
trace_partially_observed
not_observed
unknown
```

这不是 Judge accuracy，而是回答：

> rubric 评价的 capability 是否能从当前 task+trace 中看到。

## 10. C/D badcase 的预期表达

### C Retrieved

如果 C 将以下 capability 加入：

```text
tool_schema_compliance
task_state_tracking
communication_formatting
safety_constraint_following
```

但这些 capability：

- 不在 Gold rubric 的当前 task concern 中；
- task 没有明确要求；
- trace 中也没有清晰的可观察行为；

则记录为：

```text
extra_unjustified 或 extra_unobservable
```

如果它们在 RuVer human rubric 中有依据，但当前 task 不适用，则记录为：

```text
human_pattern_supported_but_task_inapplicable
```

### D Global profile

如果 D 只保留：

```text
type_system_reasoning
code_editing
integration
validation
completion_reporting
```

则预期：

```text
capability set 更紧凑
Gold overlap 可能更高
extra/unobservable capability 更少
```

但这只是待验证假设，不能预先写成结论。

## 11. 与现有分析的关系

### 与 rubric alignment 的关系

已有 alignment 回答：

```text
Human criterion ↔ Generated criterion
```

Capability alignment 回答：

```text
Criterion ↔ Capability
```

两者互补：

```text
human criterion overlap
→ capability overlap
```

当文字 rubric 不同但表达同一 capability 时，capability alignment 可以识别潜在重合。

### 与 B Judge stability 的关系

B stability 只在第二阶段 join：

```text
capability overlap
+ rubric criterion stability
```

CapabilityAlignmentAnalyst 阶段不能读取：

```text
Judge score
flip
Gold correctness
```

避免循环解释：

```text
C flip 了
→ 所以 C capability 不对
```

### 与 Gold 的关系

Gold 只作为一个 rubric set 的 reference scope，不把 Gold label 当 capability 信息。

## 12. 首轮输出

建议生成：

```text
capability_alignment.jsonl
capability_sets.jsonl
capability_overlap_metrics.json
capability_badcases.jsonl
CAPABILITY_ALIGNMENT_REPORT.md
```

每条 badcase 至少说明：

```text
- task_id
- rubric_set
- criterion_id
- capability_id
- relation
- task support
- trace observability
- Gold overlap status
- issue tag
- explanation
```

## 13. 首轮成功标准

首轮不是追求高分，而是确认角色能回答：

1. C 比 Gold 多评价了哪些 capability？
2. D 比 C 少了哪些 capability？
3. A/C/D 哪些 capability 与 Gold 重合？
4. 多出来的 capability 是 task-supported、human-pattern-supported，还是 unjustified？
5. generated rubric 评价的 capability 是否在 trace 中可观察？
6. 哪些 C/D badcase 是 capability mismatch，而不是 Judge reasoning failure？

## 14. 约束

本阶段禁止：

```text
修改 Gold
修改 B Judge
新增 Judge protocol
用 prediction/accuracy 反推 capability
把 capability overlap 当作 agent capability 分数
把 capability taxonomy 当作 human intent ground truth
```

## 15. 当前建议

先对：

```text
agents-spy-type-annotations
```

做 Gold/A/C/D 四组 capability alignment pilot。

确认单 task 上能够清楚解释：

```text
C 为什么多出 process/tool capability
D 为什么更紧凑
Gold 与 generated 的 capability overlap 到底是多少
```

之后再扩展到 v3 的 10 个 task。

## 16. CapabilityAlignmentAnalyst 字段与能力定义（冻结补充）

本节是 `CapabilityAlignmentAnalyst` 的操作性说明。分析调用必须把字段定义和 capability 定义一并提供给模型，不能只提供 capability 名称，避免模型仅凭名称自行猜测边界。

### 16.1 输出字段含义

| 字段 | 含义 | 禁止的解释 |
|---|---|---|
| `task_required_capabilities` | 当前 task 明确要求或完成 task 基本需要的 capability 集合 | 不是 agent 已经具备或已经完成这些能力的判断 |
| `trace_observed_capabilities` | 在输入 runtrace 中出现了可观察行为、足以指向该 capability 的集合 | 不是行为正确、满足 rubric 或 Gold 为真的判断 |
| `criterion_mappings` | 对每个输入 criterion 的评价对象进行 capability 映射；每个 criterion 必须恰好出现一次 | 不是 criterion satisfaction judgment |
| `criterion_id` | 原样复制输入 criterion 的标识 | 不得重新编号或按 Gold/Judge 结果修改 |
| `primary_capability` | 最能代表该 criterion 核心评价关注点的一个、最具体 capability | 不得选择宽泛标签作为默认兜底 |
| `secondary_capabilities` | criterion 文本确实同时独立评价的辅助 capability，最多两个 | 不得因为 task 或 trace 中出现相关行为就添加 |
| `criterion_scope` | criterion 评价的对象类别：`task_outcome`、`agent_process`、`tool_policy`、`validation`、`communication`、`safety`、`other` | 不等同于 evidence source，也不等同于 capability |
| `task_required` | 当前 criterion 映射的 capability 是否由 task 要求 | 不表示 agent 是否完成 |
| `trace_observed` | 当前输入 trace 是否能观察到该 capability 相关行为 | 不表示该行为是否正确 |
| `trace_observability` | `observed`=有清晰证据；`partial`=只有不完整或间接证据；`not_observed`=没有找到相关 trace 证据；`unknown`=输入不足以判断 | 不得把 not observed 写成“不满足” |
| `confidence` | 对“criterion 到 capability 映射”的置信度 | 不是对 Gold、Judge 或 agent 表现的置信度 |

### 16.2 当前 AgenticCoding capability 定义

以下定义与代码中的 `CAPABILITY_DEFINITIONS` 同步冻结。定义描述“何时使用这个标签”，不描述 agent 是否表现出该能力。

| capability | 操作性定义 |
|---|---|
| `repo_navigation` | 查找并定位相关 repository 文件、目录或模块 |
| `context_inspection` | 在决定或行动前读取相关代码、配置、文档或已有输出 |
| `requirement_parsing` | 将 task 指令和约束转化为明确要求或检查项 |
| `planning` | 在执行前或执行中选择并组织行动方案 |
| `scope_control` | 将修改和行动限制在请求范围内，避免无关变更 |
| `file_read_before_write` | 修改目标文件前检查该文件或相关上下文 |
| `code_editing` | 在合适文件中实施请求的代码修改 |
| `multi_file_integration` | 协调多个文件、模块或接口的修改，使其共同工作 |
| `type_system_reasoning` | 推理类型、注解、接口或静态类型约束 |
| `implementation_design` | 选择或应用实现请求行为所需的结构设计 |
| `tool_selection` | 为请求的操作选择合适工具或命令 |
| `tool_schema_compliance` | 按工具要求的参数、schema 和调用契约使用工具 |
| `tool_result_use` | 使用真实工具输出决定或调整后续行动 |
| `parallel_action_coordination` | 协调并行执行的动作、依赖关系和结果 |
| `task_state_tracking` | 跟踪执行中已完成、待处理或失败的事项 |
| `test_execution` | 执行请求修改对应的测试或测试命令 |
| `lint_build_validation` | 执行或检查 lint、typecheck、build 或等价的静态/打包验证 |
| `artifact_verification` | 根据 task 要求检查生成的文件或其它交付物 |
| `failure_recovery` | 识别执行失败并采取适当修复或恢复动作 |
| `completion_reporting` | 准确报告已完成工作、结果、限制或剩余问题 |
| `communication_formatting` | 按请求格式和信息要求组织最终响应 |
| `safety_constraint_following` | 遵守明确的安全、保密或禁止操作约束 |
| `dependency_management` | 管理所需包、依赖、版本或依赖相关修改 |
| `other` | 确实被 criterion 评价但无法由上述标签表示的能力；必须在 reason 中解释，不得宽泛兜底 |

### 16.3 GDPval capability 定义

GDPval 使用独立的 deliverable-oriented capability 坐标系。调用 `capability_prompt` 时，应通过 `capability_definitions=GDPVAL_CAPABILITY_DEFINITIONS` 传入，不能把 AgenticCoding capability 列表与 GDPval 列表混用。

| capability | 操作性定义 |
|---|---|
| `requirement_parsing` | 识别 task 明确提出的交付要求、约束和验收条件；不判断是否完成 |
| `artifact_creation` | 创建并交付 task 要求的目标 artifact 本身；不表示 artifact 的具体内容、格式、公式或质量 |
| `spreadsheet_structure` | 组织 spreadsheet 的工作表、行列、区域和布局结构；不表示公式数值是否正确 |
| `formula_design` | 设计或配置 spreadsheet 中的公式、引用和计算逻辑；不表示最终数值已经核对正确 |
| `financial_calculation` | 根据财务规则、输入和期间进行金额、余额、折旧或其它财务数值计算；不表示展示格式 |
| `source_data_extraction` | 从给定源文件、表格、记录或材料中识别并提取 task 所需数据 |
| `reconciliation` | 将多个数据源、表格、期间或汇总结果核对、对应并解释差异 |
| `monthly_schedule_reasoning` | 按月或按期间推导、排列和维护时间序列 schedule 中的业务关系 |
| `account_classification` | 依据 task 或领域规则将项目、交易或账户归入适当类别 |
| `file_format_compliance` | 使交付文件满足要求的文件类型、命名、可打开性或格式契约；不表示文件内容正确 |
| `artifact_validation` | 对最终 artifact 进行检查或验证，以发现其是否满足要求；不等同于具体业务计算或格式设计 |
| `numeric_precision` | 控制数值精度、舍入、显示位数或数值一致性；不等同于完整财务计算 |
| `cross_sheet_integration` | 在多个 worksheet 或 artifact 部分之间建立并保持正确的引用、联动或一致关系 |
| `presentation_formatting` | 控制 artifact 的视觉呈现、格式、样式、可读性或版式 |
| `comment_annotation` | 在 artifact 中添加要求的注释、说明、批注或来源标记 |
| `completion_reporting` | 报告交付物已生成、包含什么、验证了什么以及仍有哪些限制；不等同于创建 artifact |
| `other` | 当前 taxonomy 无法表示但 criterion 确实评价的能力；必须在 reason 中说明，不能作为宽泛兜底 |

其中 `artifact_creation` 的边界特别严格：criterion 的核心谓词必须是“创建/生成/交付/提交 artifact 本身”。如果核心谓词是“包含、计算、链接、核对、格式化或验证”，应优先使用更具体的 capability。

### 16.4 调用约束

- 代码默认保留原有 AgenticCoding capability 列表，保持向后兼容；GDPval 调用显式传入 `GDPVAL_CAPABILITY_DEFINITIONS`。
- 本次补充只增加定义和 prompt 说明，不修改 Gold、task、trace、已有 mapping、B Judge 或任何 protocol。
- 在重新运行分析前，应先人工核对定义边界；旧 mapping 结果保持为历史结果，不与使用冻结定义的新结果混合。
