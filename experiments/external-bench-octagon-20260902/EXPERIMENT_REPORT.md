# DEVAI + AgencyBench → AgentOctagon 实验报告

- 日期：2026-09-02
- 运行器：`/home/yang/agent-octagon`
- 场景仓库：`/home/yang/agent-octagon-envs`
- 执行语义：**每个 task 内并行启动 3 个 agent**；每个 task 一个 AgentOctagon run，run 的 `execution=parallel`。
- agent：`claude-code`、`codex`、`blade-agent`
- 同一模型身份：`deepseek/deepseek-v4-flash-0731`；因三种 adapter 协议不同，使用 provider-qualified mapping。
- timeout：900 秒；capture：metadata。
- scorer：`external-octagon-scorer-v1`，由 AgentOctagon 自动进入 scoring pipeline。

## 任务选择

- DEVAI：实例 51–55，共 5 个。
- AgencyBench：`AgencyBench-v2/Code/scenario1`–`scenario5`，共 5 个。
- 适配后的 10 个 env 与输入 digest 见 `dataset_manifest.json`。
- 实验定义见 `experiment_manifest.json`。

## AgentOctagon run

| 来源/任务 | run | run 状态 | claude-code | codex | blade-agent |
|---|---|---:|---:|---:|---:|
| AgencyBench 1 reaction-rate | `run_4494274cd73a` | completed | 32 | 32 | 32 |
| AgencyBench 2 repo-review | `run_3fef66d7435e` | completed | 8 | 100 | 30 |
| AgencyBench 3 event-generator | `run_967c548637ff` | completed | 40 | 15 | 40 |
| AgencyBench 4 graph-algorithm | `run_9c7adf0a309f` | failed | 40 | 100 | timeout |
| AgencyBench 5 deep-research | `run_79007f0dc2ea` | completed | 40 | 40 | 39 |
| DEVAI 51 hidden-messages | `run_f4d382ebf582` | failed | cli_error | cli_error | 92 |
| DEVAI 52 qlora | `run_bb12590e61ff` | completed | 100 | 85 | 38 |
| DEVAI 53 road-damage | `run_692b673660e7` | failed | cli_error | cli_error | 100 |
| DEVAI 54 OpenAI response analyzer | `run_f9c32a82acbf` | completed | 55 | 25 | 92 |
| DEVAI 55 SQLite viewer | `run_f0b19af169a5` | failed | 100 | 88 | interrupted |

## 聚合（仅对有 score_total 的 attempt）

| agent | 有效分数数 | 平均 score_total |
|---|---:|---:|
| claude-code | 8/10 | 51.875 |
| codex | 8/10 | 60.625 |
| blade-agent | 8/10 | 57.875 |

## 执行完整性与限制

这批结果已经由 AgentOctagon 实际执行并评分，但不是 10×3 全部成功的完整平衡矩阵：

1. DEVAI 51 与 53 的 `claude-code` 出现 `unrecognized_model`；同时 `codex` 因任务提示涉及图像输入而出现上游 endpoint 不支持 image input。
2. AgencyBench 4 的 blade attempt 超过 execution deadline。
3. DEVAI 55 的 blade session 等待显式用户输入，被 AgentOctagon 标记为 interrupted。
4. 因此平均分只能作为本次 pilot 的观测结果，不能称为完整 baseline，也不应直接用于 agent 间显著性比较。

完整轮询快照位于 `run_status.json`，提交请求与 run/attempt ID 位于 `submitted_runs.json`。历史结果未覆盖。
