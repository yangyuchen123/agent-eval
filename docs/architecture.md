# 架构：评测核心 → Meta-evaluation

## 项目沿革（请先阅读）

**AgentEval 是在 [HarnessEval-W](https://github.com/mirros-lab/HarnessEval-W) 之上用两天重新开发的项目**。HarnessEval-W 是一个世界模型视频评测框架。完整来源表见
[DESIGN_MEMORY.md §1.5](DESIGN_MEMORY.md)。项目内容分为三类：

- **继承的思想**：agentified evaluation（case → 路由后的 skills → evidence tree）、基于 digest 的结果缓存、原子写入；
- **重构的部分**：`protocols`（dict → dataclasses）、`skills/base`（module+contract → `RuleSkill`/`LLMSkill` + role）、`planner`（LLM planner → 确定性的 `RuleRouter`）、`runner`/`io` 缓存、`backends`（VLM/CLIP → 新的 OpenAI-compatible `LLMBackend`）；
- **两天内新增的部分**：数据驱动的 `FineGrainedRubric` 层、`history`、`analysis`（诊断/迁移）、`capabilities`、`manifest`、`cli`，以及 SWE-bench 和 GDPVal case package；
- **数据**：`examples/` 中的所有内容（SWE-bench instances、GDPVal cases、rubrics、pi predictions）都是在本项目中加入的；HarnessEval-W 的视频 benchmark/run 数据没有随项目迁移。

本项目是**评测编排壳**，不是 agent framework，也不是独立 Judge。当前身份边界见
[SYSTEM_BOUNDARIES.md](SYSTEM_BOUNDARIES.md)：eval-system 负责运行/采集，AgentEval
负责适配/组织/聚合，Agent Judge 负责证据检索与判断。下面的分层描述的是 AgentEval
内部的 rubric / history / diagnostics 能力，不是“把 agent 改进闭环做进本仓库”。

本项目是**评测基础设施**，而不是 agent framework。这个边界是有意设计的：

```text
             Agent Improvement System        ← 不在本项目范围内（消费层）
                      │
              Feedback / Repair Loop
                      │
             ┌────────▼────────┐
             │   AgentEval     │   ← 本项目
             │  Evaluation Core│
             └───────┬─────────┘
        ┌────────────┼────────────┐
        │            │            │
   Rubric        History      Skills
   Engine        Store        Evaluator
```

## 为什么不把 agent iteration 放进来

Agent self-iteration（“使用评测结果改进 agent”）是可以建立在任何 evaluator（SWE-bench、human preference、safety 等）之上的控制系统。将它混入评测框架，会同时引入 benchmark、judge、database 和 agent framework 的职责，边界会迅速失控。因此它应位于依赖 AgentEval 的独立仓库中：

```text
agent-improvement/
    └── loop:  agent.revise( feedback( AgentEval.evaluate(...) ) )
```

## 当前包含的能力

| 阶段 | 层 | 回答的问题 | 状态 |
| --- | --- | --- | --- |
| 1 | Rubric as data | 如何定义和版本化评测标准？ | ✅ 已完成 |
| 2 | Evaluation history | 得分是多少、使用哪个 rubric 版本、何时产生？ | ✅ 已完成 |
| 3.1 | Rubric diagnostics | 哪些问题具有区分度？（variance/entropy/corr） | ✅ 已完成 |
| 3.2 | Judge reliability | κ / ρ / self-consistency | ✅ 已完成 |
| 3.3 | Rubric version migration | 不同版本之间是否保留排序？ | ✅ 已完成 |
| 3.4 | Capability layer | 如何按潜在能力跨 benchmark 聚合？ | ✅ 已完成 |
| 3.5 | Run manifest + capability schema | 什么产生了这份报告，如何复现？ | ✅ 已完成 |
| 4 | Rubric optimization | LLM 提议修改、人工批准 | 计划中 |

命名上使用 **rubric optimization**（校准），而不是“self-evolving”，以避免过度承诺。

## 第一层：Rubric as data（当前）

- `src/agenteval/rubrics.py`：`Rubric`、`RubricQuestion`、`ScoreAnchor`、`RubricStore`。新的 reliability-sensitive question 可以声明结构化离散 `score_anchors`，同时兼容旧式文本 anchor。该模块还负责版本化 JSON 的加载、保存、校验以及 evidence-matching 工具。
- `src/agenteval/skills/rubric.py`：`FineGrainedRubric` 基类，提供 analyze/verify 两阶段流程、离散评分梯度、带防伪造约束的逐字证据和加权聚合。新的 rubric skill 通常只需要一个 JSON 文件和约 15 行子类代码。
- `examples/swebench/rubrics/patch_quality.json`：与框架代码解耦的领域 rubric 数据。

## 第二层：Evaluation history（已完成）

`src/agenteval/history.py` 使用追加式 JSONL，不依赖数据库，记录：

```text
run_id, model_id, case_id, skill_id, rubric_id, rubric_version,
score, subscores, status, judge, timestamp
```

Runner 会自动写入。查询接口包括：`by_skill`、`by_rubric`、`question_stats`、`rubric_question_report`、`summary_by_skill`，这些正是第三阶段所需的输入。

## 第三层：Rubric diagnostics（已完成）

`src/agenteval/analysis.py` 和 `agenteval analyze` CLI 提供：

- 每个问题的 variance / entropy / difficulty / distribution；
- **discrimination** = corr(question, total)，即一个 IRT 风格的 item-quality proxy。低 variance 可能意味着所有人都很好、rubric 太容易或 judge 过于宽松；与总分的相关性可以帮助区分这些情况；
- 基于规则的 verdict：`ceiling`、`floor`、`noisy`、`keep`、`insufficient_data`。

报告由人工读取和决策；当前还没有自动生成 rubric。

## Judge reliability（已完成）

`judge_rule_agreement` 会按 case 配对 LLM judge 分数与 history 中的 rule-based skill 分数：

- 对阈值化 pass/fail verdict 计算 Cohen's κ；
- 对原始分数计算 Spearman ρ。

可靠的 judge 可以得到 κ=1.0；总是判定通过的 judge 得到 κ=0.0。κ 可以暴露普通 accuracy 不容易发现的系统性宽松。当没有失败样本、所有 case 都通过时，κ 未定义（p_exp=1），报告会明确说明这一点。

Self-consistency（重复评分的标准差）需要多次运行数据，当前只有基础结构。

## Rubric version migration（已完成）

```bash
agenteval migrate --history ... --skill patch_quality --old-version v1 --new-version v2
```

该命令将两个 rubric 版本下的同一批 case 配对，并回答：**v1 的结论能否继承到 v2？**

- ranking preservation：Spearman ρ + Kendall τ，这是主要信号；绝对分数可以漂移，但排序应尽量保持；
- score drift：均值和逐 case delta，并区分 `systematic`（同号）与 `mixed`（rubric 逻辑改变）；
- question changes：从记录的 subscores 判断 removed/added/shared；
- large disagreements：找出 |Δ| 超过阈值的 case。

数据模型中的 `RubricQuestion.lineage` 保存跨版本的 ancestor ids，为未来的 proposer 做准备。

**进入第四层的门槛**：至少 50 个 case、3 个 agent、2 个 rubric 版本；低于此规模时，LLM 提议的 rubric 很容易学到噪声。

## Capability layer（已完成）

`RubricQuestion.capabilities` 使用潜在能力标签，使跨 benchmark 分析更有意义。例如，SWE-bench 的 `Q3_minimality` 和 GDPVal 的 `I17_formula_correctness` 都可以标记为 `numerical_accuracy`。这样 `capability_report` 回答的是“哪些 agent 能力退化了”，而不是“某个 benchmark 得了多少分”。

当前记录但尚未实现的扩展点：

- **Artifact abstraction**：现在 skill 输入主要是文本（`patch`/`report`）；图片、幻灯片、仓库和数据流水线等 artifact 需要 `ArtifactSet` 层，但 `evaluate(case, output)` 边界暂时保持不变；
- **Capability rollup**：taxonomy 树中从子能力汇总到父能力的功能暂缓，待数据量足够后再做；taxonomy schema 已在 `agenteval.capabilities` 中就位；
- **JudgeContract**：DeepSeek 曾从 prompt 复制 `{"Q1": ...}` 示例结构并重命名问题，造成 judge 输出污染。长期方案是独立于 prompt 的 schema validator + repair layer；当前由 `parse` 负责补偿。

## 第四层：Rubric optimization（计划中）

LLM 根据分析结果提议 rubric 修改（重写 anchor、拆分/合并问题、调整权重），人工批准后生成新版本；新版本在采用前需要与旧版本进行 agreement 评测。

## Run manifest + capability schema（已完成）

- `src/agenteval/manifest.py`：`EvaluationRun` 记录 run_id、agent（name/version）、environment（日期/机器/平台/Python）、benchmarks，以及 evaluator_snapshot（本次 history 中出现的 rubric version、judge model 和 evaluator version）。`run_eval` 会自动写入 `run_manifest.json`；CLI 支持 `--agent-name`、`--agent-version`、`--benchmark`。
- `src/agenteval/capabilities.py`：`Capability`（id/description/parent）和 `CapabilityStore`（taxonomy JSON 的加载、校验和树结构），并提供默认 taxonomy（software_engineering → code_*；document_production → format/numerical/...）。问题标签可以根据 ontology 校验；层级 rollup 暂缓，在数据门槛满足前不自动执行。

它回答了一个工业化问题：**这份报告是在什么条件下产生的？** 每次运行都可以审计，包括谁、什么、何时、使用哪个 rubric 和 judge。
