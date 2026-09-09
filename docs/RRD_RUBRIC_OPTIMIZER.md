# RRDRubricOptimizer

`RRDRubricOptimizer` 是一个独立的 response-driven rubric optimization
模块。它不改 Generator、Gold、B Judge 或现有 AgentEval taxonomy。

## RRD faithful core

```text
initial rubrics
  -> evaluate every rubric on a frozen response pool
  -> broadness test: satisfied_count > configurable N
  -> recursive decomposition of broad criteria
  -> re-evaluate children on the same pool
  -> weak-over-strong misalignment filtering
  -> exact / semantic redundancy filtering
  -> behavioral correlation warning + correlation-aware weighting
```

**Broadness 与 discrimination 是两个不同操作。** 当前 broadness 不再使用
`discrimination <= threshold` 作为前置条件，而使用：

```text
support_count > broad_satisfied_count_threshold
```

默认 `broad_satisfied_count_threshold=2`，对应论文描述的“超过预设数量的
sample responses 满足”这一类规则。`discrimination = strong_rate - weak_rate`
只用于 child measurement diagnostics 和 misalignment 分析。

当：

```text
weak_support_rate > strong_support_rate + misalignment_margin
```

criterion 会被记录为 weak-preference misalignment，并在启用
`enable_misalignment_filter` 时删除。

行为向量相似不再直接删除 rubric。它只生成：

```text
behaviorally_redundant_warning
```

同时 `correlation_aware_weights` 使用带 ridge 的 covariance precision
weighting，按 preference-edge signal 降低高度相关 rubric 的重复权重。这是
不依赖 numpy 的工程近似；不是把 correlated criteria 当作无效 criteria。

## RRD Core 与 AgentEval Adapter

RRD core 位于 `src/agenteval/rrd_optimizer/`，只知道 `Rubric`、
`CalibrationResponse` 和 satisfaction matrix。AgentEval adapter 只负责把
`criterion` schema 转成 RRD 输入，并在 optimized rubric 返回时恢复原字段和
`source_criterion_id`。

## Standalone RRD initial baseline

如果不提供 `--rubrics`，可以使用：

```bash
PYTHONPATH=src python -m agenteval.rrd_optimizer \
  --initial-generate \
  --task-id <task-id> \
  --task-file task.txt \
  --responses calibration_responses.json \
  --out run/rrd/standalone_initial_optimized.json
```

这条路径先用 `task + frozen sample responses` 生成 RRD initial rubric proposal，
然后再进入同一个 optimizer。它和现有 A/C/D Generator 条件保持分离。

若要优化既有 A/C/D rubric，则使用：

```bash
PYTHONPATH=src python -m agenteval.rrd_optimizer \
  --task-id <task-id> \
  --task-file task.txt \
  --rubrics initial_rubrics.json \
  --responses calibration_responses.json \
  --out run/rrd/optimized.json
```

## Evidence protocol

Runtrace 是可选项，不是 RRD 默认输入。GDPval 这类 artifact-centric task 默认：

```text
include_runtrace = false
require_artifact = true
broadness_quality_groups = ("strong",)
```

含义：

- evaluator / decomposer 只看交付物摘要，不看 agent 过程 trace；
- 没有 xlsx 或 xlsx 读不到的 sample 记为 `artifact_status != present`，该 response 对所有 rubric 强制 0；
- broadness 只统计 strong 组满足数；weak 组只用于 misalignment / discrimination；
- `agent_prose` 可以附带，但不能替代缺失 artifact。

需要过程证据的 task 再显式打开 `--include-runtrace`。不要把 GDPval 的 B Judge trajectory 协议复制进 RRD calibration。

## Backend

正式 RRD 调用默认使用 PydanticAI typed backend：

```bash
pip install -e ".[rrd]"
PYTHONPATH=src python -m agenteval.rrd_optimizer --backend pydantic_ai ...
```

`--backend urllib` 只保留为无 PydanticAI 环境的兼容路径，不是 GDPval 实验默认。

## Guardrails

- evaluator 每轮按 batch 调用，不按 rubric 单独调用；
- child 数、depth、iteration、expansion ratio 全部 config 化；
- child 必须重新评估，但不要求 discrimination gain 才能被接受；
- discrimination gain 保存在 decomposition trace 中作为诊断；
- exact/high-text-overlap criteria 可以删除；behavioral correlation 不直接删除；
- RRD core 不读取 grounding、scope、hardness、judgment_type、capability 等
  AgentEval 字段作优化决策；
- `middle` response group 仅作为诊断，discrimination 仍严格使用 strong-vs-weak。

## 输出

输出 JSON 包含：

```text
optimized_rubrics
satisfaction_matrix
rubric_metrics
rubric_weights
behavioral_warnings
decomposition_tree
dropped_rubrics
optimization_trace
manifest
```

并生成 condition-specific：

```text
optimization_trace_<output-stem>.jsonl
```

## 论文复现边界

当前实现复现的是 response-based decomposition、misalignment filtering、
redundancy handling 和 weighting 的核心结构。文本 semantic filtering 使用
本地确定性相似度；response satisfaction 由注入 evaluator 决定。真正的
GDPval artifact-aware evaluator 需要由上层 adapter 提供，不能把 artifact-centric
task 简化成只看 final prose。
