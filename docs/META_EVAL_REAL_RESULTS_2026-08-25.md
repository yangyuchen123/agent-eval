# Meta-Evaluation Real Run Results — 2026-08-25

本报告来自 AgentOctagon 的真实 attempt：

```text
attempt: att_3f38a0fe1604
env: agent-workspace-smoke-test
trace: /home/yang/agent-octagon/data/attempts/att_3f38a0fe1604/trace.jsonl
model: gpt-5.6-luna
```

使用真实 `.env` 配置运行 Agentic Evidence Judge，未使用 TestModel。结果保存在：

```text
run/meta_eval/octagon-real/agent-workspace-smoke-test/
run/meta_eval/octagon-real/agent-workspace-smoke-test-order/
run/meta_eval/octagon-real/agent-workspace-smoke-test-length2/
```

## 结果摘要

| snapshot | n | mean | std | min | max | status agreement | evidence Jaccard | claim agreement | latency |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| original | 5 | 0.2400 | 0.2275 | 0.0 | 0.5 | false | 0.3253 | 0.1183 | 35.5s |
| order shuffle | 3 | 0.2667 | 0.2517 | 0.0 | 0.5 | false | 0.0370 | 0.0417 | 42.1s |
| trace 2x (invalidated) | 3 | 0.1667 | 0.2887 | 0.0 | 0.5 | false | 0.3333 | 0.0000 | 31.0s |

这不是 Gold accuracy 结果，因为该 question 还没有人工 GoldJudgment。它是
当前 Agentic Judge 的真实稳定性/可解释性结果。

## 观察

### 1. 同一固定 snapshot 的 Judge 结果明显不稳定

原始 snapshot 的 5 次结果为：

```text
0.00 / 0.50 / 0.35 / 0.00 / 0.35
```

status 在：

```text
unverified
partially_supported
```

之间切换。这个结果已经足以把该 case 标记为：

```text
R12 stochastic_instability
```

但不能仅凭它判断 Judge 哪一次是正确的；需要人工 Gold 才能进一步区分
R1/R2/R3/R6/R10。

### 2. Query trajectory 显示 Judge 几乎只使用 search

这三轮实验中，Judge 的调查主要是：

```text
search_evidence
```

没有稳定使用：

```text
get_evidence
get_call_context
get_related_evidence
```

这与之前的诊断一致：当前 Judge 常常在 broad search 后直接形成 judgment，
没有稳定地展开 candidate evidence。

### 3. 原始 snapshot 中出现“trace 中有事件但搜索为空”的运行

至少一轮中，Judge 的搜索结果多次为：

```text
result_ids = []
```

随后给出：

```text
score = 0.0
status = unverified
```

但对应的真实 `trace.jsonl` 有 11 条 runtime events，且包含完整的：

```text
Read arguments/result
Bash arguments/result
文件写入
测试执行
submit_result
```

这说明该轮至少存在一个候选问题：

```text
search environment failure
```

具体表现是：Judge 用英文语义搜索任务分配/交接/恢复，但该 trace 的关键
描述主要是中文，当前 lexical search 没有把合理的英文意图映射到这些内容。
这需要与 Judge investigation failure 分开，不应先通过评分规则掩盖。

### 4. Evidence order 和 trace length 目前都没有稳定性保证

仅改变 snapshot 记录顺序后：

```text
pairwise evidence Jaccard = 0.0370
claim agreement = 0.0417
```

旧版增加记录到 2x 后（该实验已作废，因为旧 perturbation 可能复制真实记录和 evidence_id）：

```text
pairwise evidence Jaccard = 0.3333
claim agreement = 0.0000
```

order 结果与原始 snapshot 的差异目前不能完全归因于 perturbation，因为每次
调用的 LLM sampling 也可能不同。但它们明确说明：当前尚不能声称 order
invariance 或 trace-length robustness 已经成立。

## 当前结论

当前最重要的可信性风险已从假设变成真实观测：

```text
1. Agentic Judge 同一输入的 score/status 不稳定；
2. claim/evidence refs 跨重复运行高度变化；
3. Judge 调查轨迹主要停留在 broad search；
4. 至少一轮存在 trace 有证据但 search 返回空的 searchability 问题；
5. 还没有人工 Gold，因此不能报告 accuracy，也不能自动决定哪一轮正确。
```

下一步应优先：

```text
1. 为这个 attempt/question 建立人工 Gold；
2. 用 query trajectory 区分 search environment failure 和 Judge investigation failure；
3. 再对至少 5 个不同 env/task 的重复组运行同样实验；
4. 暂不通过 mandatory query 或 deterministic score policy 修复结果；
5. Gold 完成后再计算 R1/R2/R3/R6/R10 的真实比例。
```

## 2026-08-26 validity correction

旧 `trace_2x` 实现会复用原始记录作为 extras，并可能产生重复 `evidence_id`。
这不满足“只增加语义无关 trace”的实验前提，因此上述 trace-2x 数值只保留作
审计记录，不再作为 robustness 证据。实现已改为注入唯一 id、无 agent/call/message
关系、显式 `meta_eval.synthetic` 来源的 unrelated no-op records；必须用新实现重跑。
