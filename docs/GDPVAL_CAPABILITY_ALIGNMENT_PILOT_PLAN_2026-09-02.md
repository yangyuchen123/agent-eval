# GDPval Capability Coverage Alignment Pilot

日期：2026-09-02  
状态：切换方案已定义；等待冻结该 task 的真实 runtrace 后执行正式 pilot。

## 1. 切换原因

RuVerBench 的 human rubric 同时包含大量 task-level 与 benchmark/system-level Agent policy criterion，导致 capability overlap 中混入：

```text
task outcome capability
agent process capability
通用 tool/system policy capability
```

GDPval 的官方 rubric 更直接围绕具体 deliverable、格式、数值、内容、文件结构和质量要求，因此更适合先验证：

> capability alignment 是否能解释 task-specific Gold rubric 与 generated rubric 的重合度。

## 2. Pilot task

第一版选用：

```text
gdpval_prepaid_amortization_official
```

本地来源：

```text
/home/yang/agent-octagon-pr127-fix/envs/gdpval-prepaid-amortization-official/tasks/gdpval_prepaid_amortization_official.json
/home/yang/agent-octagon-pr127-fix/envs/gdpval-prepaid-amortization-official/private/official_rubric.json
```

该 task 的 official rubric 有 56 条人工 criterion，主要涉及：

```text
xlsx deliverable
worksheet structure
formula linkage
GL reconciliation
monthly amortization
account classification
formatting
comments
```

## 3. 本轮比较对象

### Gold

GDPval official rubric，作为：

```text
R_H = official GDPval rubric evaluated capability set
```

这里的 Gold 指 official rubric scope，不等于把所有 rubric item 的 score 直接作为 capability label。

### A/C/D generated rubric

本轮沿用 rubric generation 的条件名称，但 memory 改为 GDPval official rubric memory，不再使用 RuVerBench memory：

```text
A = GDPval task-only generation
C = GDPval retrieved similar-task official rubric examples
D = GDPval global official-rubric profile
```

对于 held-out task：

```text
自己的 task/rubric 必须从 GDPval memory 中排除
```

## 4. 输入边界

四组分析使用同一个：

```text
task
runtrace
rubric set
```

CapabilityAlignmentAnalyst 不能看到：

```text
rubric satisfaction Gold
B Judge score
Judge prediction
accuracy
```

它只输出：

```text
T = task-required capabilities
O = trace-observed capabilities
R_H/R_A/R_C/R_D = rubric-evaluated primary capability sets
```

## 5. GDPval capability 坐标系

GDPval 第一版只使用与 deliverable 相关的 capability：

```text
requirement_parsing
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
other
```

仍然遵循：

```text
每条 criterion = 1 primary capability + 最多 2 secondary capabilities
```

主指标只使用 primary capability。

## 6. 三个主集合

```text
T = task-required capability set
O = trace-observed capability set
R_H = Gold official-rubric primary capability set
R_A/R_C/R_D = generated-rubric primary capability set
```

核心指标：

```text
GoldCapabilityCoverage_X = |R_H ∩ R_X| / |R_H|
TaskSupport_X = |R_X ∩ T| / |R_X|
Observability_X = |R_X ∩ O| / |R_X|
```

另外报告：

```text
unique primary capability count
mean capability multiplicity
max capability multiplicity
redundancy
extra capability set
missing Gold capability set
```

## 7. 与 RuVer pilot 的关键区别

RuVer pilot 中 Gold primary capabilities 主要是：

```text
tool_selection
parallel_action_coordination
tool_schema_compliance
scope_control
dependency_management
```

GDPval official rubric 预期主要是：

```text
artifact_creation
spreadsheet_structure
formula_design
financial_calculation
reconciliation
numeric_precision
artifact_validation
```

因此 GDPval pilot 可以检验：

> 当 Gold rubric 本身与 task deliverable 高度绑定时，A/C/D 的 capability overlap 是否更容易解释，且是否减少通用 policy 噪声。

## 8. 不能在没有真实 trace 时执行的部分

正式的 `O = trace-observed capabilities` 需要该 task 的真实冻结 runtrace。

当前已找到：

```text
task 文件
official rubric
输入文件
```

但当前 `agent-eval` 工作区没有找到该 GDPval task 对应的冻结 Agent runtrace 文件。因此暂时不能伪造：

```text
trace_observed_capabilities
Observability_X
```

也不能用 task 文本替代 trace。

如果只做 task+official rubric 的静态映射，只能得到：

```text
T
R_H
```

不能完成本角色的完整 pilot。

## 9. 正式执行顺序

拿到或定位该 task 的真实 runtrace 后：

```text
1. 冻结 task digest / rubric digest / trace digest
2. 建立 GDPval official-rubric memory
3. 排除 held-out task
4. 生成 A/C/D rubric
5. 对 Gold/A/C/D 做 capability mapping
6. 计算 capability overlap
7. 对 C/D 做 badcase analysis
8. 再决定是否进入 B Judge stability
```

本轮只做一个 task，不扩展数据集。

## 10. 产物

```text
run/gdpval-capability-alignment-pilot-20260902/
├── experiment_manifest.json
├── task.json
├── official_gold_rubric.json
├── runtrace.jsonl
├── generated_rubrics_A.json
├── generated_rubrics_C.json
├── generated_rubrics_D.json
├── capability_alignment.json
├── capability_overlap_metrics.json
├── capability_badcases.jsonl
└── GDPVAL_CAPABILITY_ALIGNMENT_REPORT.md
```

## 11. 当前执行结论

GDPval 是更合适的下一阶段 benchmark，因为它能把：

```text
Gold rubric scope
```

更直接地锚定到：

```text
task deliverable capability
```

但正式 pilot 必须使用真实 task+trace。当前先不使用空 trace、不把 task 描述冒充 trace，也不把 official rubric 的 requirement 直接当作 observed capability。
