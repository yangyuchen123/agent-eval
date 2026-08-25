# Autonomous Judge Investigation Instruction Experiment

日期：2026-08-25

本实验只修改 Judge system instruction，未修改 EvidenceCatalog，未增加 mandatory tool call、question-specific retrieval、depth threshold 或 deterministic scoring。

## 实验设置

同一个真实案例：

```text
run/launch-readiness-decomposition-v1/attempt/
```

使用真实模型：

```text
gpt-5.6-luna
```

两种 instruction 各运行两轮：

```text
old: 原有 autonomous Judge instruction
new: 增加 candidate evidence / sufficient evidence / discovery→verification / observed-derived-inferred-missing 自检原则
```

## 结果

| mode | scores | 平均 search | get | context | related | depth |
|---|---|---:|---:|---:|---:|---|
| old | 0.91, 0.91 | 5.0 | 0 | 0 | 0 | 1, 1 |
| new | 0.86, 0.91 | 5.0 | 0 | 0 | 0 | 1, 1 |

两种 instruction 的四轮运行中：

```text
get_evidence = 0
get_call_context = 0
get_related_evidence = 0
investigation_depth = 1
```

## 结论

### 1. instruction 没有可靠地诱导 verification behavior

虽然新 instruction 明确写入了：

```text
Search results are candidate evidence, not proof by themselves.
Semantic relevance is not sufficient to establish a runtime relation.
```

但真实模型仍然主要执行：

```text
broad search → final judgment
```

没有稳定进入：

```text
search → get/context/related → final judgment
```

### 2. 分数有轻微下降，但不能证明证据判断已经改善

旧 instruction：

```text
0.91, 0.91
```

新 instruction：

```text
0.86, 0.91
```

新 instruction 的一次运行分数降低，并且输出了更多 missing evidence，但两轮仍然将主要 claims 标记为 `supported`，不能据此认为 evidence sufficiency 已经解决。

### 3. 当前问题仍然主要是 Judge investigation failure

本实验没有发现新的 search environment failure。Evidence Tool 能够返回真实的 Agent call、artifact read/write 和 tool result。

当前更准确的诊断是：

```text
Evidence environment 可用
Judge 看到了候选证据
Judge 没有稳定展开候选证据
Judge 仍然容易把相关证据升级成 supported
```

### 4. 没有把 depth 变成评分规则

本实验只记录：

```text
search_count
get_count
context_count
related_count
investigation_depth
```

没有实现：

```text
depth < 3 → 降分
get_context == 0 → 禁止 supported
```

## 当前决策

暂时不继续增加：

```text
mandatory query
mandatory tool call
question-specific retrieval
verify_handoff
automatic proof
```

下一步如果继续优化，应优先研究：

```text
为什么模型在看到候选 Agent call 后没有选择 get/context/related；
如何通过更清晰的工具描述、返回结构和 agent interaction design 提高自主 verification 概率；
而不是把 verification 流程编码进 EvidenceCatalog。
```

完整原始结果见：

```text
run/launch-readiness-preference-study/investigation_instruction_experiment_2026-08-25.json
```
