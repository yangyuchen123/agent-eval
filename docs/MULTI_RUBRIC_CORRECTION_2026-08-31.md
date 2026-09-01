# 多 rubric 研究方向修正记录

日期：2026-08-31
状态：current

## 结论

此前把 HealthBench、RuVerBench DeepResearch、RuVerBench AgenticCoding 的每个样本适配为“一个 request + 一个 rubric”，执行上是可用的，但研究解释上不完整。

该结构应被定义为：

```text
mechanical single-rubric adapter baseline
```

而不是外部 benchmark 的最终语义结构。

## 为什么需要修正

当前 AgentEval 已经存在：

- planner；
- RubricPlanner；
- RuleRouter / LLMRouter / RubricRouter；
- 多个 RubricQuestion；
- MultiQuestionJudgeSkill；
- criterion-level routing；
- weighted aggregation；
- per-question provenance。

因此如果外部 benchmark 原本提供 task-level、多 criterion 或多 rubric 信息，继续永久压缩为单 rubric 会混淆两个问题：

1. Judge 本身是否判断正确；
2. adapter 是否丢失了任务原有的 rubric 结构。

## 正确的研究对照

```text
M0 机械单 rubric
M1 黄金多 rubric
M2 黄金 rubric + dynamic rubric planner
M3 黄金 rubric + skill router + multi-question judge
```

M0 必须保留，因为它是当前已有结果的可复现基线；M1/M2/M3 只在有可追溯的原始 rubric、task metadata 或已有 provenance 时构造，不得凭空伪造 Gold criterion。

## 最小执行原则

1. 固定同一 60 个 case、Gold、response/trajectory、Judge model/provider 和 score-to-binary mapping。
2. 先比较 M0 与 M1；只有 M1 有提分证据，才继续 M2/M3。
3. 不新增 parallel orchestrator；复用现有 planner/router/multi-question judge。
4. 评价主指标仍是最终 Gold accuracy，内部误差分析只做辅助解释。
5. 如果原始 benchmark 的多 rubric 无法可靠恢复，应明确标记为 unavailable，而不是用人工猜测补齐。

## 当前错误执行的修正

此前若直接把单 rubric 条件当作唯一正式结构，等于没有测试系统已经具备的 task-level planner/router 能力。后续实验应把该方式降级为对照条件，并把黄金多 rubric、动态 rubric 和 skill router 作为有明确提分假设的候选条件。
