# AgentEval 文档索引

状态：current  
更新时间：2026-08-31

## 当前有效文档

| 文档 | 用途 |
|---|---|
| `DOC_MANAGEMENT_STANDARD.md` | 文档、脚本、实验和归档管理标准 |
| `AGENT_CONTRACT.md` | Agent 输入输出和行为契约 |
| `DESIGN_MEMORY.md` | 当前设计记忆与约束 |
| `INTERFACES.md` | 系统接口和数据边界 |
| `JUDGE_ARCHITECTURE.md` | Judge 架构说明 |
| `META_EVALUATION.md` | Meta-evaluation 当前入口 |
| `CURRENT_JUDGE_ACCURACY_LIFT_PLAN.md` | 当前 60-case Judge 正确率提升与消融主计划 |
| `MULTI_RUBRIC_CORRECTION_2026-08-31.md` | 将机械单 rubric 降为 baseline，并恢复多 rubric / planner / router 对照方向 |
| `GOLD_DATASET_REDESIGN_PLAN_2026-08-31.md` | 60-case Gold 数据集的 task/criterion 分层、多 rubric 视图和抽样方案 |
| `RUNTIME_ADAPTERS.md` | Runtime evidence adapter 当前说明 |
| `SYSTEM_BOUNDARIES.md` | 系统边界和职责划分 |
| `architecture.md` | 项目架构总览 |

## 当前研究入口

当前研究不直接使用根目录旧实验报告。请先查看对应 archive index：

```text
archive/2026-08-31/judge-research/ARCHIVE_INDEX.md
archive/2026-08-31/project-history/ARCHIVE_INDEX.md
```

## 已归档研究线

| 归档 | 内容 | 当前状态 |
|---|---|---|
| `archive/2026-08-31/judge-research/` | 外部 Judge 方法相容性与 factorial error decomposition | frozen / blocked by dataset design |
| `archive/2026-08-31/project-history/` | 历史 meta-eval 文档、脚本和 run 产物 | historical |

## 使用规则

- 当前实现依据只引用本索引中列出的 current 文档；
- 日期命名的实验文档默认是 historical/experimental，不自动代表当前方案；
- 报告中的路径必须能通过 archive index 或 experiment manifest 追溯；
- 需要运行历史脚本时，优先从归档 canonical copy 执行，根目录 wrapper 仅用于兼容。
