# Bundled Question vs Single Question Experiment

日期：2026-08-25

本实验验证一个假设：之前 Judge investigation depth 偏浅，是否主要因为一个 subjudge 同时承担了多个 rubric 维度。

## 实验设置

固定：

```text
case: att_8c7d922fac35
trace: run/launch-readiness-decomposition-v1/attempt/
model: gpt-5.6-luna
```

对比：

```text
bundled question:
  task decomposition + assignment + result recovery + downstream consumption

single question:
  result_recovery_quality only
```

每种 question scope 分别使用：

```text
old instruction
investigation-aware instruction
```

本轮每个条件运行 1 次，是方向性实验，不是稳定性统计。

## 结果

| Scope | Instruction | Score | Status | Search | Get | Context | Related | Depth |
|---|---|---:|---|---:|---:|---:|---:|---:|
| bundled | old | 0.86 | partially_supported | 4 | 0 | 0 | 0 | 1 |
| bundled | new | 0.93 | supported | 6 | 0 | 0 | 0 | 1 |
| single | old | 1.00 | supported | 5 | 0 | 0 | 0 | 1 |
| single | new | 1.00 | supported | 5 | 0 | 0 | 0 | 1 |

## 结论

### 1. 单个 question 没有自动带来更深的 investigation

bundled 和 single 两组都没有调用：

```text
get_evidence
get_call_context
get_related_evidence
```

四个条件的 investigation depth 都是：

```text
1
```

因此当前不能认为“多个 rubric 放在一个 Judge 中”是浅层调查的唯一原因。

### 2. single question 反而给出了更高分

`result_recovery_quality` 单问题在 old/new 两种 instruction 下都是：

```text
score = 1.0
status = supported
```

但它同样只有 broad search，没有 evidence expansion。因此这个 1.0 不能被解读为证据链更充分；它反而说明单问题缩小 scope 后，Judge 更容易将搜索到的相关记录概括成 supported。

### 3. 新 instruction 仍然没有改变工具调查轨迹

在 bundled 条件下，新 instruction 从 0.86 提升到 0.93；在 single 条件下仍为 1.0。但四个条件都保持：

```text
search only
```

因此 instruction 没有诱导出 discovery → verification 行为。

### 4. 当前假设的状态

```text
“多 rubric bundling 是浅层调查的唯一原因”：暂不支持
“多 rubric bundling 可能影响 claim breadth 和 score calibration”：仍然可能
“Judge 本身不会主动展开证据”：目前仍被实验支持
```

single-question Judge 仍然可以出现：

```text
search
  ↓
相关 Agent calls / result 文本
  ↓
supported = 1.0
```

所以 evidence sufficiency failure 并没有因为缩小 question scope 自动消失。

## 后续建议

下一轮应重复每个条件至少 3 次，并对 single-question 的 claims 做逐条 evidence audit，尤其检查：

```text
child_calls_and_results
parent_collection
downstream_use
```

不能仅依据 score 或 status 判断 single-question 模式已经改善。

本实验没有修改：

```text
EvidenceCatalog
mandatory tool calls
question-specific retrieval
verification workflow
deterministic score policy
```

原始结果：

```text
run/launch-readiness-preference-study/scope_experiment_2026-08-25.json
```
