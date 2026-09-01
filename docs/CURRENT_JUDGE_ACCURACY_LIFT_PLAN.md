# 当前 Judge 正确率提升研究计划

状态：current  
版本：`accuracy-lift-v1`  
日期：2026-08-31

## 1. 唯一主目标

在已经冻结的 60 个 Gold case 上，提高现有 AgentEval Judge 的最终判定正确率。

当前主指标是：

```text
primary: binary accuracy
secondary: balanced accuracy, positive F1, Gold MAE
```

这不是当前阶段的主目标：

- 解释每个错误到底属于 evidence retrieval、rubric interpretation 还是 semantic inference；
- 证明某个模块解决了哪一种内部测量误差；
- 重新设计 benchmark；
- 修改 Harbor/Pi；
- 建立新的 Gold 标注体系。

## 2. 当前研究对象

固定：

```text
60 个 Gold case
Gold label
case/question/response/trajectory
benchmark source
Judge model/provider
基础 AgentEval 服务
```

主要数据集：

```text
HealthBench                         20
RuVerBench DeepResearch             20
RuVerBench AgenticCoding            20
```

这 60 条是主 accuracy benchmark。Octagon failure-handling case 只作为 runtime regression fixture，不纳入 60-case headline accuracy。

## 3. 研究策略

先建立一个尽可能强的 baseline，再逐个加入外部研究中已经验证过的模块，比较能否提升 60-case accuracy。

### 3.1 重要修正：单 rubric 是适配 baseline，不是最终评价结构

此前将三个外部 benchmark 统一适配为：

```text
一个 request + 一个 rubric
```

这只是为了接入当前 Judge API 的机械适配条件，不应被误认为是这些 benchmark 的原始 rubric 结构，也不应成为唯一正式实验条件。当前 AgentEval 已有 planner、router、RubricPlanner、RubricRouter 和 MultiQuestionJudgeSkill，可以承载一个 task 对应多个 rubric question、多个 skill 以及加权聚合。

因此本研究需要明确区分：

```text
M0 mechanical single-rubric
    当前适配方式；作为最低基线和对照条件

M1 gold multi-rubric
    尽量恢复/整理原始 benchmark 的 task-level rubric 结构，
    由多个 criterion/question 共同判定同一个 response/trajectory

M2 gold multi-rubric + dynamic rubric planner
    在黄金 rubric 骨架上，由 planner 根据 task、response/trace 和 rubric context
    选择或补充本题需要的判定问题；不得无约束改变 Gold 定义

M3 gold multi-rubric + skill router + multi-question judge
    将不同 criterion 路由给已有 skill/evidence 能力，再聚合 criterion-level judgments
```

这些条件不是为了凑消融矩阵，而是为了回答一个直接的提分问题：

> 当前 60-case Judge 的错误，是否部分来自把原本的多 rubric/task-level 评价机械压缩成一个 rubric；恢复黄金 rubric、动态 rubric 和现有 planner/router 后，最终 Gold accuracy 是否提升？

当前系统已经具备上述能力的代码基础，因此下一步应优先复用现有 planner/router，而不是继续设计新的 rubric 拆分器或新的 orchestrator。机械单 rubric 条件必须保留，作为对照实验，用来比较：

1. 机械单 rubric；
2. 黄金多 rubric；
3. 黄金 rubric + 动态 rubric；
4. 黄金 rubric + skill router / multi-question judge。

实验仍然只以冻结的 60 个 Gold case 的最终 accuracy 为主指标。内部的 evidence retrieval、rubric interpretation 和 semantic inference 分析只用于解释提分或退化，不能替代 accuracy 验收。

总体形式：

```text
同一 60 case / 同一 Gold
→ baseline Judge
→ 加入一个候选方法
→ 比较 accuracy / balanced accuracy / F1 / MAE
```

当前阶段允许使用整段 trajectory/trace 作为 Judge 输入。原因是先建立较高的可比基线，而不是优先优化 evidence retrieval 或结构化 evidence。

## 4. Baseline 与消融条件

### B0：当前生产/历史 baseline

```text
现有 Judge prompt
现有 rubric
现有 evidence/input representation
现有 score-to-binary mapping
```

### B1：full-trace baseline

将可用的 response、trajectory、artifact summary 和 runtime trace 尽可能完整地放入 Judge 输入。

目的：

- 建立“证据不受检索限制”的强 baseline；
- 判断简单扩大 Judge 可见上下文能否提升最终 accuracy；
- 作为后续结构化 EvidenceRecord 的上界/参照条件。

这不是生产建议，只是 accuracy ablation condition。

### B2：anchor prompt ablation

固定档位数量，比较 anchor wording：

```text
old wording
vs
qualitative wording
vs
explicit positive/negative boundary wording
```

当前假设：anchor prompt 可能比档位数量本身更影响正确率。

### B3：rubric presentation ablation

在不改变 Gold 的情况下比较：

```text
原始 rubric
rubric + explicit decision rule
rubric + positive/negative examples
rubric + counterexample guidance
```

这里只比较最终 accuracy，不要求当前阶段解释内部错误来源。

### B4：reference / judge protocol ablation

受控比较：

```text
rubric-only
rubric + task reference
rubric + answer/check reference
```

每个 condition 单独记录，不能混成同一个结果。

### B5：JRH-style reliability protocol

先不把它当作提分模块，而是作为测量协议：

```text
repeat
order shuffle
evidence/trace length variation
irrelevant context addition
```

主实验仍以原始条件 accuracy 为主；稳定性作为 guardrail，防止提分来自随机波动。

### B6：structured trajectory evidence

在 full-trace baseline 之后，再比较：

```text
serialized trace
vs
structured EvidenceRecord
vs
structured EvidenceRecord + full trace summary
```

如果 structured evidence 降分，也不立即认为它更“科学”；当前阶段首先记录 accuracy 结果。

### B7：calibration / threshold post-processing

在 Judge raw score 已保存的前提下比较：

```text
fixed threshold
threshold sweep
Platt/logistic calibration
isotonic calibration
```

必须使用独立 split 或 cross-validation，不能用同一 60 条拟合并报告同一批数据的提升。

## 5. 外部研究与当前目标的关系

| 外部方法 | 当前用途 | 是否直接作为提分候选 |
|---|---|---|
| JRH | repeat、扰动和可靠性报告协议 | 主要是评测协议 |
| RubricEval | rubric 类型分层、hard/easy 分析 | 是，作为 rubric prompt/分层参考 |
| SAJA | calibration head | 是，但排在强 baseline 和 prompt 消融之后 |
| Conformal Judge | uncertainty/abstention | 暂不作为主 accuracy 提升模块 |
| JudgeLM | reference、swap、position bias | 是，作为受控 prompt protocol 消融 |
| AgentRewardBench | trajectory 评价维度和完整 trace 输入思路 | 是，优先用于 AgenticCoding |

外部方法的验收标准只有一个：

```text
在相同 60-case Gold 上，是否带来可重复的 accuracy 提升，且没有不可接受的稳定性/成本退化。
```

## 6. 实验顺序

### Phase 0：整理 60-case baseline

冻结并统一：

- case order；
- Gold label；
- response/trajectory 输入；
- rubric version；
- anchor prompt version；
- model/provider/config；
- input digest。

### Phase 1：建立强 baseline

依次运行：

```text
B0 current baseline
B1 full-trace baseline
```

先回答：完整上下文是否本身就能提分。

### Phase 2：恢复 task-level 多 rubric 结构

优先选择能够从现有 benchmark 原始材料或已有 adapter provenance 中恢复的 case，先做最小 paired experiment：

```text
M0 mechanical single-rubric
vs
M1 gold multi-rubric
```

固定 Judge model、Gold label、response/trace、anchor 和 binary mapping，只改变 rubric presentation / orchestration。

验收重点：

- 总体 accuracy 是否提升；
- 哪些 case 从错变对、哪些从对变错；
- 是否只是改变了判定阈值；
- 是否有 benchmark 子集严重退化。

只有 M1 显示明确提分，才继续测试：

```text
M1 vs M2: dynamic rubric planner
M1/M2 vs M3: skill router + multi-question judge
```

### Phase 3：prompt / anchor 消融

在当前最好的 rubric topology 上，针对已观察到的 badcase 做最小 prompt 改动：

```text
best rubric condition + anchor wording
best rubric condition + explicit decision guidance
best rubric condition + reference protocol
```

每次只改一个条件；如果多 rubric 本身已经解决主要错误，不再无关地扩展 prompt 消融。

### Phase 4：组合最优条件

仅当单项改动分别有证据支持时，才组合：

```text
best rubric topology
+ best anchor / decision guidance
+ best reference condition
```

组合前必须保留各单因素结果，避免无法归因。

### Phase 5：trajectory/evidence 表示

只在强 baseline 和 prompt 条件稳定后比较：

```text
full serialized trace
vs
structured EvidenceRecord
```

### Phase 6：calibration

最后再对 raw score 做 threshold/calibration，不覆盖 raw output。

## 7. 主报告格式

每个实验必须至少报告：

```text
condition
changed_variable
frozen_components
n_total
n_scored
accuracy
balanced_accuracy
positive_f1
gold_mae
per_benchmark accuracy
confusion matrix
per-case transition
latency/cost
stability guardrail
```

核心比较表：

| Condition | Changed variable | Accuracy | Balanced Acc | F1 | MAE | Stability | Cost |
|---|---|---:|---:|---:|---:|---:|---:|
| B0 | current | - | - | - | - | - | - |
| B1 | full trace | - | - | - | - | - | - |
| B2 | anchor wording | - | - | - | - | - | - |

## 8. 结果解释边界

当前优先报告：

```text
哪种 Judge 条件在 60 个 Gold case 上更准确
```

不要在没有额外设计的情况下声称：

```text
某模块降低了某种内部 inference error
某模块解决了 evidence retrieval
某模块改善了 rubric understanding
```

这些可以作为后续分析问题，但不是本阶段验收条件。

如果某个模块提分但无法解释原因，仍然是有效的工程/实验结果；只要：

- 输入和 Gold 冻结；
- changed variable 清楚；
- 对照条件存在；
- 结果可复现；
- 没有数据泄漏。

## 9. 当前停止条件

若某条件在 60 case 上没有改善，且没有稳定性或成本优势，则暂不继续扩大该方向。

若某条件提升 accuracy：

1. 先在相同 60 case 上重复确认；
2. 检查 per-benchmark 是否只改善一个子集；
3. 检查是否增加 FP/FN 偏置；
4. 检查是否因 threshold 或 label mapping 产生假提升；
5. 再决定是否进入生产候选。

## 10. 当前结论

当前研究不是先回答：

```text
Judge 为什么错？
```

而是先回答：

```text
在相同 Gold 上，哪些已有研究模块和 prompt protocol 能把 Judge 的正确率真正提上去？
```

误差归因、structured evidence 理论、calibration 和 uncertainty 都服务于后续解释和改进，不应阻塞第一阶段的 accuracy benchmark。

---

# 11. 研究纪律：不为消融而消融

消融实验不是本项目目标，也不是必须完成的清单。唯一目标是：

> 找到能够在冻结 60-case Gold 上带来真实、可重复正确率提升的最小改动。

## 11.1 只有有提分假设才做实验

每次实验开始前必须先写一个可证伪假设：

```text
因为当前 Judge 在某类 case 上存在某种可观察的系统性错误，
所以加入某个具体改动后，60-case accuracy 应该提升。
```

如果没有明确的错误模式、改动机制和预期指标，不启动该消融。

## 11.2 外部方法不是待打勾的功能列表

JRH、RubricEval、AgentRewardBench、SAJA、JudgeLM 等只在以下情况下引入：

- 它们针对当前 60-case 上已经观察到的错误；
- 它们能形成一个最小改动；
- 它们不需要重新运行 Harbor/Pi；
- 它们有明确的 baseline 和 success metric。

如果某个外部方法与当前错误无关，则只保留文献记录，不实施。

## 11.3 实验选择顺序

每轮只选择一个当前最可能提分的改动：

```text
观察 60-case badcase / confusion matrix
→ 提出一个具体错误假设
→ 选择一个最小改动
→ 在相同 60 cases 上运行
→ 比较 accuracy、F1、FN/FP 和成本
→ 提升则保留，否则停止该方向
```

不允许为了凑实验矩阵而同时运行：

```text
anchor 改动
+ rubric 改动
+ reference 改动
+ evidence 改动
```

## 11.4 默认优先级不是固定的

以下顺序只是候选，不是必须执行的路线：

1. full-trace baseline：仅当当前输入确实缺失有效 response/trajectory/trace；
2. anchor/rubric wording：仅当 badcase 显示边界理解或 partial case 错误；
3. reference：仅当 Gold 所需事实已存在但 Judge 无法利用；
4. structured trajectory：仅当 serialized trace 对 coding case 造成明显噪声；
5. calibration：仅当 raw score 与 binary decision 的阈值偏差是主要问题。

如果第一项已带来足够提升，后续不继续横向扩展。

## 11.5 通过标准

单次偶然提分不算成功。候选改动至少要检查：

- 总体 accuracy 是否提升；
- 是否只是把 FN 变成 FP；
- 三个 benchmark 是否出现严重退化；
- 主要 badcase 是否改善；
- 是否引入明显的稳定性或成本退化；
- 是否能在固定输入上复现。

只有满足这些条件，才进入下一轮验证或生产候选。

## 11.6 当前停止规则

以下情况直接停止继续做该方向：

- 没有明确提分假设；
- 改动没有改善 60-case 主指标；
- 只改善一个 case 但整体恶化；
- 提升完全来自 threshold 投机或标签泄漏；
- 引入成本明显增加但没有稳定收益；
- 结果无法归因到当前改动。

因此当前不追求：

```text
完成所有外部方法
完成完整消融矩阵
做出漂亮的方法对比表
```

只追求：

```text
用最少实验找到能真实提分的改动。
```
