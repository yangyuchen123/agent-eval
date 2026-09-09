# Judge Accuracy Lift 研究阶段结论与关闭记录

状态：closed / frozen
日期：2026-09-01

## 1. 关闭范围

本记录关闭当前这一轮“继续通过 A/B/C/D protocol 变化挖掘 Judge 正确率提升”的研究阶段。

关闭并不表示 AgentEval Judge 已经达到最终正确率，也不表示所有误差已经解决；它表示当前数据和证据已经足够支持一个稳定 baseline，继续在同一批 Gold 和同一组 protocol 上横向试验，预期信息增益不足。

本阶段不再继续：

- 优化 A/B/C/D Judge protocol；
- 新增 E/F/G protocol；
- 基于当前 20-task validation 继续调 prompt、threshold 或 evidence policy；
- 将 all-wrong case 直接当作 protocol failure；
- 以 filtered accuracy 替代 raw benchmark accuracy。

## 2. 冻结实验资产

### Observation set

```text
19 tasks
109 criteria
```

路径：

```text
run/meta_eval/whole-task-multirubric-coding19-20260901/
```

### Non-overlap validation set

```text
20 tasks
77 criteria
overlap with observation set = 0
```

路径：

```text
run/meta_eval/conditional-validation-coding20-20260901/
```

该目录包含：

- A/B/C/D frozen results；
- feature and transition analysis；
- oracle analysis；
- validation comparison report；
- manual all-wrong review；
- criterion validity / observability audit。

## 3. Frozen protocol definitions

```text
A = per-rubric judging + full trajectory
B = joint multi-rubric judging + full task-level trajectory
C = shared evidence collection + joint scoring
D = shared evidence collection + per-rubric scoring
```

四个条件使用同一 shared runner、同一 Gold、同一 task/trajectory 输入和同一 score threshold。

## 4. 主要结果

### 19-task observation set

```text
A = 67.89%
B = 70.64%
C = 67.89%
D = 70.64%
```

### 20-task non-overlap validation set

```text
A = 75.32%
B = 84.42%
C = 76.62%
D = 76.62%
```

validation 上的顺序为：

```text
B > C = D > A
```

B 使用 20 次 model calls；A 使用 77 次；C 使用 40 次；D 使用 97 次。

当前结果支持：

> 保留完整 task-level context 的 joint multi-rubric judging（B）是当前较强且调用次数显著更少的 baseline。

当前结果不支持：

> evidence/scoring 拆分或 adaptive protocol routing 已经产生稳定、可复现的额外收益。

## 5. Oracle 与 routing 判断

```text
19-task oracle gain = 6.42pp
20-task validation oracle gain = 2.60pp
```

在 validation 中：

```text
multiple protocols correct = 61 / 77
all protocols wrong = 10 / 77
only B correct = 4
only A correct = 1
only C correct = 1
only D correct = 0
```

因此当前不实现 adaptive router。validation 的理论互补收益只有 2.60pp，尚不足以抵消 router 的复杂度、额外验证成本和归因风险。

## 6. 误差解释边界

Judge accuracy 的剩余误差不能全部归因于 Judge reasoning。人工复核和 validity audit 显示，误差还受到：

- execution 是否完成；
- required input 是否存在；
- criterion trigger 是否出现；
- trajectory 是否覆盖所需行为；
- Gold 是 observed execution 还是 normative expectation；
- Gold 与当前冻结 trajectory 的语义/完成态是否对齐。

尤其是 validation 中四个 protocol 全部失败的 10 条 criterion：

- 全部是 Gold=True / prediction=False；
- 多数 trajectory 没有提供足够的正例观察；
- 有些 trajectory 足以看出 agent 未完成，但 Gold=True 与 observed execution 存在张力；
- 不能把这 10 条全部称为 Judge semantic failure。

人工复核结论见：

```text
run/meta_eval/conditional-validation-coding20-20260901/MANUAL_ALL_WRONG_REVIEW.md
```

## 7. 当前可正式使用的研究结论

> 在 AgenticCoding trajectory evaluation 中，保留完整 task-level context 的 joint multi-rubric judging 是当前较强且成本显著更低的 baseline；进一步拆分 evidence/scoring 或进行 protocol routing，目前没有表现出足够稳定的收益。Judge accuracy 的剩余误差显著受到 execution observability 和 Gold/trajectory alignment 影响。

这里的“成本显著更低”在当前记录中主要由 model call topology 支持：

```text
B=20 calls vs A=77, C=40, D=97
```

当前结果没有完整 token usage / provider cost，因此不把 monetary cost 写成已验证事实。

## 8. 研究阶段状态

```text
status: closed_for_current_protocol_accuracy_lift
baseline: B
new_protocol_search: stopped
current_data: frozen
```

后续只有在研究问题发生变化时才重新开启，例如：

- 新的 Gold 数据集或明确的 observed-execution 标注；
- 独立的 criterion validity / observability 研究；
- 新的 agent trajectory evaluation 任务；
- 明确的人类校准或 evaluator uncertainty 研究。

如果只是修改 Judge prompt、evidence routing 或 protocol 实现，应该先复用现有 frozen replay 资产，并单独建立新的 experiment manifest；不得覆盖本记录中的结果。
