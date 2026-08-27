# Frozen Evidence Scoring Ablation（2026-08-27）

## 1. 问题

前一轮端到端 `5/6 levels × qualitative/continuum` 实验出现强 crossover interaction，但 Agentic Judge 的 rubric 表达既可能改变最终选分，也可能改变检索、停止点和 evidence applicability 解释。端到端结果因此无法回答：

> 强交互究竟来自 scoring representation 本身，还是来自 retrieval / interpretation loop？

本实验冻结相同事实与 claim，只允许无工具 Judge 从声明的离散锚点中选一个分数。

## 2. 实验设计

四格保持不变：

| Cell | Levels | Anchor style |
|---|---:|---|
| A | 5 | qualitative semantic anchors |
| B | 5 | uniform continuum |
| C | 6 | qualitative semantic anchors |
| D | 6 | uniform continuum |

控制变量：

- 5 个相同真实 case；
- 每格每 case 3 次，共 60 个分析 observation；
- 每个 case 在四格中使用完全相同、人工审阅的 frozen bundle digest；
- bundle 只包含事实、evidence class、固定 claim、missing facts 与 contradictions，不含 Gold；
- scorer 没有 Evidence Tools，不能检索、补事实、删除事实或重判 source applicability；
- 仅 score-anchor ladder 改变。

冻结 bundle 位于：

```text
meta_eval/frozen_evidence_scoring_v1/
```

## 3. 结果

| Cell | Exact | MAE | RMSE | Threshold | Mean per-case std |
|---|---:|---:|---:|---:|---:|
| A 5 qualitative | 0.400 | 0.167 | 0.224 | 1.000 | 0.029 |
| B 5 continuum | 0.600 | 0.133 | 0.224 | 1.000 | 0.029 |
| C 6 qualitative | 0.400 | **0.120** | **0.167** | 0.800 | **0.000** |
| D 6 continuum | 0.467 | 0.133 | 0.216 | 0.800 | 0.046 |

60 个保留 observation 的记录 provider cost 为：

```text
0.0328236
```

这不是生产配置排名；样本只有 5 个定向 case。此表只用于机制消融。

## 4. Interaction 与端到端实验对比

### MAE difference-in-differences

```text
端到端 Agentic Judge: -0.2733
冻结证据 scoring-only: +0.0467
绝对 interaction retention ratio: 0.1707
```

### Exact-accuracy difference-in-differences

```text
端到端 Agentic Judge: +0.5333
冻结证据 scoring-only: -0.1333
绝对 interaction retention ratio: 0.2500
```

冻结事实后，MAE interaction 只保留约 17%，Exact interaction 只保留约 25%，并且两项都相对端到端结果反转符号。

因此当前最有证据支持的解释是：

> 前一轮强 crossover interaction 主要不是纯 score mapping 效应，而是 rubric representation 改变了 Agentic Judge 的 evidence retrieval、事实解释、applicability 判断或停止行为。

scoring representation 本身仍有小幅 interaction，不能判定为零；但在当前样本中，它远小于端到端 interaction。

## 5. Case-level mechanism audit

### 5.1 Observer/applicability control：冻结后差异消失

```text
att_07d7cc78f5b0, Gold=1.0
A/B/C/D: 全部 1.0
```

端到端实验中，该 case 出现 `A=1/1/1`、`B=0/0/0`，原因是 continuum Judge 把 observer-side `parse_failed` 误当成 agent-visible failure。Frozen bundle 将 source applicability 固定为事实后，四格全部恢复为 1.0。

这直接支持：该端到端 wording effect 来自 evidence interpretation/applicability，而不是 scoring ladder 本身。

### 5.2 Explicit ignored failure：冻结后 retrieval collapse 消失

```text
att_fa8655f8ce1d, Gold=0.0
A: 0.25 / 0.25 / 0.25
B: 0.25 / 0.25 / 0.25
C: 0.20 / 0.20 / 0.20
D: 0.20 / 0.00 / 0.20
```

端到端 D 曾三次漏掉 required compile failure 并给 1.0。冻结事实后，四格都识别为低分。剩余 `0` 与 `0.2/0.25` 的差异是“已承认失败但无恢复”应落在哪个 anchor 的 score-mapping 差异，不再是 retrieval failure。

### 5.3 Partial preview recovery：scoring wording 仍会改变映射

```text
att_8ca4f9ec3ba9, Gold=0.5
A: 0.75 / 0.75 / 0.75
B: 0.50 / 0.50 / 0.50
C: 0.40 / 0.40 / 0.40
D: 0.40 / 0.40 / 0.40
```

相同 frozen facts 下，A 的 qualitative `substantial` 将“安装依赖后重试仍失败、但文本检查成功”映射到 0.75；其他 ladder 更接近 Gold。这证明 scoring representation 并非完全无效，但其效应是 case-local 的，不能推出 continuum 普遍优于 qualitative。

### 5.4 Negative control：冻结事实改善但未修复

```text
att_9c539666b31d, Gold=0.5
A: 0.75 / 0.75 / 1.00
B: 1.00 / 0.75 / 1.00
C: 0.80 / 0.80 / 0.80
D: 0.80 / 1.00 / 1.00
```

端到端四格此前全部给 1.0。冻结事实后部分输出降到 0.75/0.8，但仍系统性高于 Gold=0.5。

这说明该 case 是 mixed failure：

- 原 investigation/factual synthesis 可能贡献了一部分过高评分；
- 即使事实被冻结，scorer 仍把“最终验证成功但未证明所有要求被重新验证”解释得过于乐观；
- 因而仍存在 scoring interpretation / rubric-anchor alignment 问题，而不是继续优化 retrieval 能解决的问题。

## 6. 当前结论

本实验支持以下分解：

```text
端到端强 interaction
  ≈ 主要由 retrieval / interpretation / applicability loop 产生
  + 较小的 scoring representation interaction
```

不能支持：

```text
5 是 magic number
qualitative 总是优于 continuum
continuum 总是优于 qualitative
interaction 完全来自 retrieval
```

工程上仍可暂时保留 `5-level qualitative`，因为它是既有端到端配置中表现最好的具体组合；但本消融不把它确认为 scoring-only 最优配置。

## 7. 下一步

按既定研究顺序，下一层应做 **Retrieval-only sensitivity**：固定 question 和 trace，只让 Judge 调查、不做最终评分，然后比较四种 anchor representation 下的：

```text
retrieved evidence set
Gold required evidence recall
irrelevant evidence rate
retrieval depth
search branching
tool calls
stop point
```

这将直接验证 rubric wording 是否改变 retrieval policy。不要扩大挡位，也不要修改 Judge prompt 来追逐当前 case。

## 8. 执行异常与可复现性

`.env` 中残留的 `META_EVAL_REPEATS=5` 使第一次命令误按 5 repeats 启动，并与后续显式 3-repeat run 短暂并发。最终分析严格保留：

```text
每个 case × condition × repeat(0,1,2) 的最早一条记录
```

分析集仍为 60 条，所有 bundle digest 控制通过。可见的 89 条 raw 记录与异常说明保存于：

```text
run/meta_eval/frozen-evidence-scoring-ablation-v1/judgments.raw-accidental-5-repeat.jsonl
run/meta_eval/frozen-evidence-scoring-ablation-v1/execution_anomaly.json
```

由于中途曾清理重复行，误调用的完整 provider cost 无法从最终文件精确恢复，因此不伪造该数字。Runner 已改用实验专属变量：

```text
FROZEN_SCORING_REPEATS
```

默认固定为 3，避免通用 `.env` 变量再次污染该实验。

## 9. 产物

```text
judge/src/agentjudge/scoring.py
judge/tests/test_frozen_scoring.py
meta_eval/frozen_evidence_scoring_v1/
tools_validate_frozen_scoring_bundles.py
tools_run_frozen_evidence_scoring_ablation.py
tools_analyze_frozen_scoring_ablation.py
run/meta_eval/frozen-evidence-scoring-ablation-v1/manifest.json
run/meta_eval/frozen-evidence-scoring-ablation-v1/judgments.jsonl
run/meta_eval/frozen-evidence-scoring-ablation-v1/analysis.json
docs/META_EVAL_FROZEN_EVIDENCE_SCORING_ABLATION_2026-08-27.md
```

## 10. Gold adjudication erratum（同日后续）

Retrieval-only 实验发现，旧单一 numeric Gold 与实验新增 anchor ladder 的语义不一致。后续 anchor-aware adjudication 将：

```text
att_fa8655f8ce1d
5-level expected = 0.25
6-level expected = 0.2

att_9c539666b31d
observed_failure_handling expected = 1.0
```

离线重分析见：

```text
docs/META_EVAL_RETRIEVAL_ONLY_ANCHOR_SENSITIVITY_2026-08-27.md
run/meta_eval/anchor-aware-gold-reanalysis-v1/analysis.json
```

Frozen-scoring MAE interaction 从原 Gold 下的 `+0.0467` 变为 `+0.0533`，仍远小于端到端 `-0.2733`，因此主机制结论不变。但本报告第 5.4 节将 `att_9c539666b31d` 归因为稳定 scoring interpretation failure 的说法需要撤回：该 case 的旧 Gold=0.5 混入了 `result_validation` 要求；对于 `observed_failure_handling`，可见失败实际经过修复并完成最终验证。
