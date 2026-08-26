# AgentOctagon 数据可用于 Meta-Evaluation

已接入一个只读 discovery adapter：

```text
src/agenteval/meta_eval/octagon.py
```

它只读取 AgentOctagon 的归档数据，不运行 agent、不调用 scorer、不修改
AgentOctagon 数据库，职责边界仍然是：

```text
AgentOctagon
  ├── attempts / trace / wire / trajectory / artifacts
  ├── envs / scorer / task
  └── octagon.db
          ↓ read-only discovery
AgentEval Meta-Evaluation
```

## 当前数据盘点（2026-08-25）

从 `/home/yang/agent-octagon` 发现：

```text
AgentOctagon environments: 84
DB attempts: 600
attempt directories: 582
attempts with trace.jsonl: 352
attempts with wire.jsonl: 529
```

其中有：

```text
49 个同 env + 同 task 的重复组
307 个属于重复组的真实 attempt
```

每个 attempt 可以关联：

```text
trace.jsonl
wire.jsonl
trajectory.json
conversation.jsonl
events.jsonl
thinking.jsonl
recovery.json
security_events.jsonl
artifact files
score_total
per-dimension scores
model
status
run/task/env metadata
```

## 先做的运行层稳定性结果

这不是 Judge 稳定性结论，而是先验证数据是否足以支持 Meta-Evaluation。
对同一个 `env + task` 的不同真实 attempt，比较 AgentOctagon 已保存的
`score_total`：

```text
repeat groups: 49
exact score agreement: 13 / 49
score range > 10: 29 / 49
score range > 25: 22 / 49
mean group score std: 15.1519
maximum score range: 100
```

最大波动的组包括：

```text
gdpval-prepaid-amortization-db       0 → 100
gdpval-source-faithfulness-db        0 → 100
name-referent-decoupling             0 → 100
visitor-appointment                  0 → 99
presentbench-academia-prompt-authoring 0 → 91
edit-contract-repair                 30 → 100
```

这证明 AgentOctagon 现有数据足够支持：

```text
真实 trace 回放
同任务跨 attempt 对比
模型/状态分层
artifact/runtime 缺失分析
Judge repeated-run stability
Evidence removal / order perturbation
```

但这些分数波动不能直接归因于 Judge，因为不同 attempt 可能改变了：

```text
被测 agent 的实际行为
模型
运行状态
输入上下文
runtime failure
确定性 scorer 输入
```

因此后续必须按以下层次拆分：

```text
Layer 1: AgentOctagon execution variance
Layer 2: deterministic scorer variance
Layer 3: Agent Judge repeated-run variance
Layer 4: Gold agreement
```

## 使用方式

生成只读 inventory：

```bash
source judge/.venv/bin/activate
PYTHONPATH=src:judge/src \
  python tools_inventory_octagon.py \
  --output run/meta_eval/octagon-inventory/inventory.json
```

分析已有真实 attempt 的运行层稳定性：

```bash
PYTHONPATH=src:judge/src \
  python tools_analyze_octagon_stability.py \
  --output run/meta_eval/octagon-stability
```

输出：

```text
inventory.json
summary.json
groups.json
```

这些输出位于 `run/` 时不会进入 Git；如果需要作为实验 artifact，应通过
meta-eval run manifest 记录其 digest。
