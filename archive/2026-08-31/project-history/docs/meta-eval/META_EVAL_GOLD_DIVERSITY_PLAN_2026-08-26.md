# Gold 数据集多样性扩充计划（2026-08-26）

## 为什么先扩充 Gold

当前人工 Gold 已经可以用于一次初步比较，但分布仍然明显偏向满分：

```text
0.0: 2
0.5: 8
1.0: 20
```

这种分布适合检查少量明确失败/成功样本，不能可靠测量 Judge 是否能区分：

```text
忽略失败
部分恢复
大部分恢复但仍有缺口
完全恢复
```

因此在继续运行 2/3/4/5 挡位或三种 Judge 对比前，先扩充 Gold 的语义多样性。

## 新的候选集

从 AgentOctagon 的 352 条真实 attempt 中重新扫描，并排除已经进入 Gold 的 attempt，生成：

```text
run/meta_eval/failure-handling-diversity-v3/
```

候选集包含：

```text
40 个 review packet
39 个不同环境
0 个已存在 Gold 的重复 attempt
```

扫描结果中的候选分层不是 Gold 标签，只是人工审阅优先级：

```text
A/B/C explicit failure with later success candidate: 21
A/B/C explicit failure without obvious later success: 5
B/C recovery outcome requires human review: 21
D expected fallback branch: 5
E nonfatal warning: 7
F exit-zero semantic failure: 9
G observer capture failure: 6
H low-score without explicit failure: 7
```

同一个 packet 可以属于多个候选分层，因此这些数字不能相加作为样本数量。

## 人工审阅目标

第一轮不把 40 个 packet 全部自动转成 Gold，而是按以下顺序人工审阅：

### 第一优先级：补充中间分数

优先从以下候选中寻找真实的 `0.5`：

```text
review_B_or_C_recovery_outcome_requires_human
review_A_B_C_explicit_failure_with_later_success_candidate
```

只有同时看到以下三类证据，才允许标为 partial recovery：

```text
1. direct failure event
2. subsequent recovery attempt
3. unresolved / unverified / incomplete resolution boundary
```

### 第二优先级：补充明确的 0 分

选择：

```text
explicit failure without successful recovery
```

要求能够直接证明：

```text
Agent saw the failure
and ignored it, blindly repeated it, or left it unresolved.
```

### 第三优先级：补充 1 分和 N/A 控制样本

补充两类对照：

```text
explicit failure → diagnosed → fixed → verified
warning/fallback/observer-side issue → not applicable
```

这样可以防止 Judge 仅因为看到 `error`、`warning` 或失败文本就降低分数。

## Gold 审阅规则

Octagon score 只用于候选发现，不用于标注 Gold。

每个确认的 Gold 必须填写：

```text
case_id
question_id
expected_score
expected_status
applicability
expected_stratum
positive_evidence_refs
negative_evidence_refs
required_evidence_refs
missing_evidence
notes
```

对 `0.5` 样本，`missing_evidence` 不能为空，并且 notes 必须说明为什么不是确定的 0 或 1。

对 N/A 样本，要明确说明为什么该事件不属于当前 question 的适用范围，例如：

```text
仅有错误结果，没有显式 operation failure
observer capture failure 对 Agent 不可见
正常 fallback 分支
```

## 下一次实验门槛

在满足以下最低分布前，不把 5 levels 的初步优势解释为普遍规律：

```text
≥ 8 个 partial-recovery cases
≥ 5 个 explicit-failure-ignored cases
≥ 5 个 fully-recovered cases
≥ 5 个 not-applicable / applicability-control cases
```

达到门槛后，使用同一批 Gold 做控制变量实验：

```text
v3: 0 / 0.5 / 1
v5: 0 / 0.25 / 0.5 / 0.75 / 1
每个 case 每个版本重复 3–5 次
```

报告：

```text
Gold agreement
MAE
per-case mean/std
anchor confusion matrix
evidence-reference overlap
status agreement
```

在 Gold 扩充阶段不修改：

```text
Judge prompt
EvidenceCatalog
Evidence tools
mandatory query policy
question-specific deterministic retrieval
```

## 可复现校验

```bash
python3 tools_validate_failure_gold.py
```

该命令只校验 Gold 文件和证据引用，不自动生成任何标签。
