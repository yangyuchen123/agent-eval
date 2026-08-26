# Multi-Case Judge Reliability Results — August 26, 2026

## Protocol

真实模型与 endpoint：

```text
model: gpt-5.6-luna
judge mode: agentic_evidence
rubric: generic-runtime-process-reliability
rubric version: frozen-2026-08-26
cases: 6 real AgentOctagon attempts
repeats: 3 per case
calls: 18
```

固定问题只评价 runtime 中可观察的 process quality，不把 AgentOctagon 的产品
scorer 直接当作 Gold。完整记录位于：

```text
run/meta_eval/octagon-real/multi-case-generic-process/
```

## Stability results

| attempt | env | Octagon status/score* | Judge scores | mean | std | status agreement | evidence Jaccard | latency |
|---|---|---|---|---:|---:|---|---:|---:|
| att_3f38a0fe1604 | agent-workspace-smoke-test | gave_up / 25 | .34/.25/.36 | .3167 | .0586 | true | 1.0000 | 40.9s |
| att_3d8ecd7a1800 | agent-parallel-scheduling | completed / 65 | .95/.92/.96 | .9433 | .0208 | true | .7020 | 31.8s |
| att_83a41bf1ced2 | validation-claim-integrity | gave_up / 73 | .94/.78/.82 | .8467 | .0833 | false | .8054 | 37.0s |
| att_9ede41110391 | edit-contract-repair | gave_up / 75 | .98/.98/1.00 | .9867 | .0115 | true | 1.0000 | 23.8s |
| att_d348670523d9 | gdpval-source-faithfulness-db | completed / 100 | .96/.92/.92 | .9333 | .0231 | true | .8182 | 20.2s |
| att_d437e26c7bbc | visitor-appointment | gave_up / 0 | .68/.64/.72 | .6800 | .0400 | true | .9048 | 43.0s |

`*` Octagon score 是不同目标的环境/product scorer，只作诊断上下文，不是这个
process question 的人工 Gold。

## What is stable and what is not

### Score/status stability improved under a frozen generic question

与 August 25 的单 case/bundled question 实验相比，这个冻结问题下：

```text
5 / 6 cases had exact status agreement
score std range: 0.0115–0.0833
```

因此不能笼统地说 Judge 在所有 case 上都高度随机。稳定性明显依赖：

```text
question scope
trace searchability
case evidence density
```

### Evidence selection is more stable than exact claim formulation

最终 evidence Jaccard 为：

```text
0.7020–1.0000
```

但旧输出中的 `claim_agreement` 实际比较的是精确 `(claim_id, status)` 集合，不是
语义 claim agreement；它的低值不能直接解释为 reasoning 完全不同。该指标已
重命名为：

```text
exact_claim_identity_agreement
```

真正的 semantic claim agreement 仍为 unavailable，需要人工映射或独立语义
评审，不能用自动字符串指标伪造。

## Query trajectory audit

跨 18 次运行：

```text
主要工具：search_evidence
get_evidence：只在 agent-parallel-scheduling 的一轮出现（12 次 get）
get_call_context：只在 edit-contract-repair 的一轮出现（1 次）
get_related_evidence：0
```

空 search 比例按 case 为：

```text
agent-workspace-smoke-test       23.1%
agent-parallel-scheduling        33.3%
validation-claim-integrity       38.5%
edit-contract-repair             33.3%
gdpval-source-faithfulness-db     0.0%
visitor-appointment               0.0%
```

这说明 broad search 仍是主调查方式，但在高信息密度的 parallel-scheduling case
中 Judge 至少有一轮自主展开了 12 个 evidence records。工具深度不是固定的，
不能用 `get == 0` 直接判错。

## High-priority sufficiency audit candidate

`att_9ede41110391` 只有三个 trace events：

```text
Read dashboard.py
Edit dashboard.py
Read dashboard.py
```

三轮 Judge 给出：

```text
0.98 / 0.98 / 1.00
supported / supported / supported
```

Judge 把 post-edit Read 视为 validation，并认为任务没有明确要求测试。这可能是
合理的 rubric interpretation，也可能是：

```text
R6 missing_evidence_failure
R9 rubric_anchor_failure
```

因为冻结 anchor 的 1.0 描述要求 strong execution and validation evidence，而
这里只有静态 readback，没有 executable validation。没有人工 Gold 时不能自动
定罪，但这是首要人工 calibration case。

## Diagnostic comparison with Octagon scorer

仅作诊断，把 Judge mean 与 Octagon product/environment score 做数值比较：

```text
MAE: 0.2433
Pearson: 0.7122
Spearman: 0.6571
pairwise ranking accuracy: 0.7333
threshold agreement: 0.8333
```

这些不是 human agreement，因为两者衡量的目标不同。例如：

```text
visitor-appointment Octagon score = 0
process Judge mean = 0.68
```

它可能意味着 Agent 做了部分可观察过程但产品失败，而不是 Judge 必然错误。

## Current reliability conclusions

1. 固定、单一、跨环境 process question 下，score/status 比之前 bundled question
   稳定，但尚未达到可忽略波动；
2. evidence refs 在多数 case 上较稳定；
3. exact claim identity 很不稳定，但 semantic claim agreement 尚未可靠计算；
4. Judge 主要依赖 broad search，relation navigation 几乎未发生；
5. 不同语言和低 evidence-density trace 仍有较高 empty-search rate；
6. 至少一个高分 case 需要人工确认“readback 是否足以成为 1.0 validation”；
7. 没有人工 Gold，不能报告 accuracy 或 R1–R10 的真实发生率。
