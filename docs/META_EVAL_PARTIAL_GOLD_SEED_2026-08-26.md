# Failure-handling 人工 Gold：partial-recovery seed（2026-08-26）

## 本次变更

在 `run/meta_eval/failure-handling-blind-v1/gold/` 增加了一个真正的 `0.5` 人工 Gold：

- `att_f7830b42a3d8`
- question：`observed_failure_handling`
- anchor：`0.5`
- stratum：`B_explicit_failure_partial_recovery`

该标签只依据 AgentOctagon 的原始 `trace.jsonl`，没有使用 Octagon 总分生成。

## 为什么是 0.5

证据链是：

1. `trace.jsonl:106`：一次 Edit 明确失败，原因是找不到预期的 `old_text`；
2. `trace.jsonl:107`：Agent 随后提交了其它变更，但没有成功重试该 Edit；
3. `trace.jsonl:108`：Agent 宣布完成，但没有给出该 `.gitignore` 修改已成功应用的验证。

因此这不是“显式失败被忽略”的确定性 `0`，也不是“每个失败都已诊断并成功解决”的 `1`。它只证明 Agent 继续推进了流程，不能证明失败操作本身已恢复，故标为 `0.5`。

这个判断只针对 `observed_failure_handling`，不代表该 attempt 的总体任务质量，也不评价其它 rubric 维度。

## 当前 Gold 分布

当前共 17 个 Gold：

- `0`：2 个；
- `0.5`：1 个；
- `1`：14 个；
- 其中 `applicable` 的显式失败样本：8 个。

因此这仍然只是 **partial-recovery seed**，不是平衡校准集。不能据此得出 2/3/4/5 挡位在 partial recovery 上的普遍结论。下一步仍需在不依赖 Octagon score 的前提下补充多个独立 partial case。

## 可复现校验

使用：

```bash
python3 tools_validate_failure_gold.py
```

该工具只检查：

- Gold JSON schema 的关键字段；
- evidence ref 是否指向真实 trace 行；
- `0.5` 是否使用 partial-recovery stratum；
- partial Gold 是否记录缺失证据。

它不会自动决定 Gold，也不会修改 Judge prompt、EvidenceCatalog 或评分逻辑。
