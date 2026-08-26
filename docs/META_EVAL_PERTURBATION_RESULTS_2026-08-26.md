# Corrected Perturbation Results — August 26, 2026

## Protocol validity

旧 `trace_2x` 实验已作废。这里使用修正后的 perturbation：

```text
unique evidence_id
source = meta_eval.synthetic
event_type = meta_eval:irrelevant_noop
no agent/tool_call/message relation
semantically unrelated heartbeat content
```

真实模型：`gpt-5.6-luna`。两个真实 AgentOctagon attempts，每种 condition 3 次：

```text
order_shuffle: 6 calls
corrected trace_2x: 6 calls
new calls: 12
```

原始 baseline 使用相同 frozen rubric 的 3 次结果。原始与扰动不是逐随机种子配对，
因此比较的是 condition-level distributions。

## Condition comparison

### att_3f38a0fe1604 — workspace smoke test

| condition | mean | std | status distribution | cross-baseline evidence Jaccard |
|---|---:|---:|---|---:|
| baseline | .3167 | .0586 | partial 3 | 1.0000 |
| order shuffle | .3667 | .0569 | partial 3 | 1.0000 |
| corrected trace 2x | .3200 | .0000 | partial 2 / contradictory 1 | 1.0000 |

```text
order mean delta: +0.0500
trace-2x mean delta: +0.0033
synthetic evidence selected: 0
```

关键发现不是 score，而是 top-level status：三次 trace-2x 都得到完全相同的：

```text
score = 0.32
11 个相同 evidence_refs
```

但 status 为：

```text
partially_supported
contradictory
partially_supported
```

claims 中都包含 supported、partial 和 contradictory 子项。这说明顶层 status 如何
从混合 claims 汇总，目前没有稳定语义。它是独立于 retrieval 的结构化输出问题，
是 R10 reasoning/aggregation 或 schema-semantics 风险候选；没有 Gold 时不自动归类。

### att_3d8ecd7a1800 — parallel scheduling

| condition | mean | std | status distribution | cross-baseline evidence Jaccard |
|---|---:|---:|---|---:|
| baseline | .9433 | .0208 | supported 3 | — |
| order shuffle | .9233 | .0252 | supported 3 | .7268 |
| corrected trace 2x | .9200 | .0520 | supported 3 | .7382 |

```text
order mean delta: -0.0200
trace-2x mean delta: -0.0233
synthetic evidence selected: 0
```

在这个高 evidence-density case 上，order 和无关 length growth 没有改变 status，
平均分变化约 0.02，但 evidence selection 仍有约 26–27% 的跨 condition 差异。

## Conclusions

1. 修正后的 synthetic noise 从未被最终 judgment 引用，perturbation 没有直接污染
   evidence chain；
2. 两个 case 的 trace-length 平均分变化很小（+0.0033、-0.0233）；
3. order shuffle 的平均分变化为 +0.0500、-0.0200，当前 N=3 尚不足以证明严格
   invariance；
4. workspace case 暴露了同 score/同 evidence 下 top-level status 不稳定；
5. parallel case 的 status 稳定，但 evidence refs 对 order/length 仍不完全 invariant；
6. 当前只能报告 robustness/stability，不能报告 correctness，因为尚无人工 Gold。
