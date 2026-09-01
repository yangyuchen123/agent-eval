# AgentEval Judge Research Archive

归档日期：2026-08-31
归档目的：将本轮外部 Judge 方法分析、factorial error decomposition 设计、真实 replay 结果和实验脚本从工作区根目录分离，形成可追溯的研究归档单元。

## 目录结构

```text
judge-research/
├── ARCHIVE_INDEX.md
├── ARCHIVE_MANIFEST.json
├── docs/
│   ├── EXTERNAL_METHODS_COMPATIBILITY_AND_INSERTION_2026-08-31.md
│   └── FACTORIAL_ERROR_DECOMPOSITION_PROTOCOL_2026-08-31.md
└── run/meta_eval/factorial-error-decomposition-v1/
    ├── experiment-manifest.json
    ├── fixture-*.json
    ├── rubric-variants/
    ├── r0e0-baseline/
    ├── r0e1-*/
    ├── r1e0-*/
    └── run_*.py
```

## 归档内容职责

| 层 | 内容 | 状态 |
|---|---|---|
| `docs/` | 外部方法相容性、互斥性、L0-L6 插入位置、factorial protocol | 设计/协议 |
| `fixtures/` | 3 个历史 runtime case 的 evidence replay candidate manifest | candidate，非完整 canonical run fixture |
| `rubric-variants/` | R0 original 与 R1 decomposed 的分析视图 | analysis-only |
| `r0e0-baseline/` | 原始 rubric + 当前 evidence 的真实 3-case replay | 已完成 |
| `r0e1-oracle-evidence/` | 过窄 curated evidence 的实验 | 已完成，标记为 invalid oracle candidate |
| `r0e1-corrected-oracle-access/` | full snapshot 但首轮 search 全量返回的实验 | 已完成，未作为正式 oracle |
| `r0e1-priority-access/` | 保留完整 snapshot、仅改变 priority/search ordering 的实验 | 已完成，evidence-access candidate |
| `r1e0-decomposed-current-evidence/` | 分解 rubric + 当前 evidence 的 9 次 Judge replay | 已完成，diagnostic-only |
| `run_*.py` | 本轮实验专用入口 | 仅限归档 replay，不是生产入口 |

## 真实实验结论摘要

```text
R0E0：2/3 exact score match
R0E1 priority-access：2/3 exact score match
R1E0：3 个分解 subscore × 3 case；subquestion 没有独立 Gold
```

当前唯一可以保留的研究观察是：`att_35f7ed7f3d24` 中 priority evidence access 使 required evidence recall 从 0 变为 1，score 从 1.0 变为 0.5，但仍未达到 Gold=0.0。这个 case 仍混合了 retrieval、recovery semantics 和 inference 问题，不能作为单一因果结论。

## 冻结边界

- 不修改生产 Judge、AgentEval、Harbor/Pi、Gold 或 benchmark generator；
- 不把 3 个 failure-handling case 当作总体 Judge Gold；
- 不把 R1 subscore 当作正式准确率；
- 不继续运行 R1E1，除非先建立更丰富、分布更合理、具有 component Gold 的数据集；
- 归档内脚本如需重跑，应明确设置 `AGENT_EVAL_ROOT=/home/yang/agent-eval`，并从 Judge virtualenv 执行。

## 来源保留规则

本归档引用现有实验产物，不复制原始 Harbor/Pi 数据。原始历史数据仍在：

```text
/home/yang/agent-eval/run/meta_eval/
/home/yang/agent-eval/meta_eval/
```

本归档中的 `source_refs`、trace digest、snapshot digest 和 Gold digest 用于追溯。 mutable `latest` 不作为依赖。

## 方向修正说明

本归档中的 factorial error decomposition 是此前阶段的探索性方案，现已冻结为历史材料。当前项目主目标已调整为：

```text
在冻结的 60 个 Gold case 上提升 Judge 最终正确率
```

新的当前主计划见：

```text
docs/CURRENT_JUDGE_ACCURACY_LIFT_PLAN.md
```

旧 factorial 实验不得阻塞 60-case accuracy ablation，也不得被解释为当前主研究目标。
