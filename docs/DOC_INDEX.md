# AgentEval 文档索引

状态：current  
更新时间：2026-09-09

## 当前有效文档

| 文档 | 状态 | 用途 |
|---|---|---|
| `DOC_MANAGEMENT_STANDARD.md` | current | 文档、脚本、实验和归档管理标准 |
| `AGENT_CONTRACT.md` | current | Agent 输入输出和行为契约 |
| `DESIGN_MEMORY.md` | current | 当前设计记忆与约束；恢复上下文入口 |
| `INTERFACES.md` | current | 系统接口和数据边界 |
| `JUDGE_ARCHITECTURE.md` | current | 独立 Judge 目标架构 |
| `META_EVALUATION.md` | current | Meta-evaluation 当前入口 |
| `RUNTIME_ADAPTERS.md` | current | Runtime adapter 与评分入口 |
| `SYSTEM_BOUNDARIES.md` | current | eval-system / AgentEval / Judge 职责划分 |
| `architecture.md` | current | 评测核心分层总览 |
| `EXPERIMENT_POLICY.md` | current | 正式实验必须用共享 runner / manifest |
| `RRD_RUBRIC_OPTIMIZER.md` | current | 独立 RRD rubric optimizer 模块说明 |

## 实验 / 提案（不作为生产契约）

日期命名文档默认是 experimental 或 closed，不自动代表当前实现。

| 文档 | 状态 | 用途 |
|---|---|---|
| `CURRENT_JUDGE_ACCURACY_LIFT_PLAN.md` | experimental | 60-case Judge 正确率提升与消融主计划 |
| `JUDGE_ACCURACY_LIFT_CLOSURE_2026-09-01.md` | closed / frozen | A/B/C/D 正确率提升阶段关闭记录 |
| `MULTI_RUBRIC_CORRECTION_2026-08-31.md` | experimental | 多 rubric / planner / router 对照方向 |
| `GOLD_DATASET_REDESIGN_PLAN_2026-08-31.md` | proposal | 60-case Gold 重构方案 |
| `FEATURE_VARIABLE_SPEC_20260901.md` | experimental | A/B/C/D slice feature 变量 |
| `RUBRIC_GENERATION_PIPELINE_PLAN_2026-09-01.md` | experimental | RuVer 人工 rubric 生成与 retrieval 方案 |
| `CAPABILITY_ALIGNMENT_ROLE_PLAN_2026-09-02.md` | experimental | capability 对齐角色方案 |
| `GDPVAL_CAPABILITY_ALIGNMENT_PILOT_PLAN_2026-09-02.md` | experimental | GDPval capability alignment pilot |
| `RUBRIC_CLASSIFICATION_TAXONOMY_2026-09-02.md` | experimental | rubric 分类 taxonomy |
| `RUBRIC_DEFECT_ATTRIBUTION_ROLE_PLAN_2026-09-03.md` | experimental | rubric defect 归因角色 |
| `RUBRIC_REFINER_PLAN_2026-09-03.md` | experimental | RubricRefiner / AtomicityValidator 实施说明 |

## 已归档研究线

| 归档 / 指针 | 内容 | 当前状态 |
|---|---|---|
| `archive/2026-08-31/judge-research/` | 外部 Judge 方法相容性与 factorial error decomposition | frozen / blocked by dataset design |
| `archive/2026-08-31/project-history/` | 历史 meta-eval 文档、脚本和 run 产物 | historical |
| `EXTERNAL_METHODS_COMPATIBILITY_AND_INSERTION_2026-08-31.md` | 归档指针 | archived |
| `FACTORIAL_ERROR_DECOMPOSITION_PROTOCOL_2026-08-31.md` | 归档指针 | archived |

## 当前真实边界（2026-09-09）

AgentEval **核心**是评测编排：`Case → Router → Skill → Evidence → History`。

- 生产评分入口：`agenteval eval`、`octagon-score`、`harbor-score`。
- 独立 Judge 契约：`JudgeRequest` / `JudgeClient` / `JudgeResponse`。
- 研究模块留在包内，但不进入核心 runner：`meta_eval/`、`rrd_optimizer/`、`rubric_*`。
- 过渡兼容，不作为目标架构：`octagon-eval`、`OctagonLLMJudgeSkill`、`RuntimeEvidenceIndex`、`infer_with_tools`。它们仍存在于 `agenteval.adapters`，但不再从包根导出。

`experiments/runner.py` 尚未落地。正式实验在共享 runner 建立前不得再复制根目录 `tools_run_*.py`。

## 使用规则

- 当前实现依据只引用本索引中的 current 文档；
- 日期命名的实验文档默认是 historical/experimental，不自动代表当前方案；
- 报告中的路径必须能通过 archive index 或 experiment manifest 追溯；
- 需要运行历史脚本时，优先从归档 canonical copy 执行，根目录 wrapper 仅用于兼容。
