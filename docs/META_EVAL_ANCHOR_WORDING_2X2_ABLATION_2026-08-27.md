# Anchor 数量 × Anchor 表达：2×2 消融（2026-08-27）

## 1. 为什么必须做这个实验

此前观察到：

```text
5-level qualitative → MAE 0.183
6-level continuum   → MAE 0.333
```

但这个对比同时改变了：

```text
anchor 数量：5 → 6
anchor wording：qualitative → continuum
```

因此 A→D 不能回答究竟是 resolution 还是 wording 导致退化。本轮补齐两个缺失条件：

|          | Qualitative semantics | Uniform continuum |
| -------- | --------------------- | ----------------- |
| 5 levels | A：已有               | B：本轮新增       |
| 6 levels | C：本轮新增           | D：已有           |

新增调用：

```text
5 cases × 2 missing cells × 3 repeats = 30 observations
recorded provider cost = 0.20262488
```

## 2. 控制变量

四格均使用：

```text
question = observed_failure_handling
model = gpt-5.6-luna
seeds = 20260825 / 20260826 / 20260827
same five case IDs
same trace digest for each case
same EvidenceCatalog / tools
same Judge policy
```

没有加入 case-specific anchor、mandatory query 或 deterministic score rule。

需要注意：seed 是 meta-eval observation 标识，并不保证外部模型生成完全可复现。四格的 agentic investigation trajectory 仍然可能不同；这正是 end-to-end Judge 对 anchor wording 敏感性的一部分，但会限制纯 scoring-stage 因果解释。

## 3. 四格结果

![Anchor wording 2×2 消融](assets/anchor_wording_2x2_ablation.png)

| Cell        | Levels | Wording     |        Exact ↑ |          MAE ↓ |         RMSE ↓ |    Threshold ↑ |     Mean std ↓ | Evidence Jaccard ↑ |
| ----------- | -----: | ----------- | --------------: | --------------: | --------------: | --------------: | --------------: | ------------------: |
| **A** |      5 | qualitative | **0.467** | **0.183** | **0.266** | **0.933** |           0.050 |               0.760 |
| B           |      5 | continuum   |           0.200 |           0.417 |           0.536 |           0.600 |           0.029 |     **0.801** |
| C           |      6 | qualitative |           0.133 |           0.373 |           0.513 |           0.600 |           0.231 |               0.603 |
| D           |      6 | continuum   |           0.400 |           0.333 |           0.507 |           0.600 | **0.023** |               0.680 |

A 是当前 end-to-end reliability 最好的组合，但最低方差出现在 D。D 的低方差包含稳定错误，因此不能把它解释为更可信。

## 4. Resolution effect

### 4.1 固定 qualitative wording

```text
A → C
5 qualitative → 6 qualitative
```

| 指标      |     A |     C |                 C − A |
| --------- | ----: | ----: | ---------------------: |
| Exact     | 0.467 | 0.133 |                −0.333 |
| MAE       | 0.183 | 0.373 | **+0.190，变差** |
| RMSE      | 0.266 | 0.513 |                 +0.246 |
| Threshold | 0.933 | 0.600 |                −0.333 |

在 qualitative semantics 下，增加到六挡明显变差。

### 4.2 固定 continuum wording

```text
B → D
5 continuum → 6 continuum
```

| 指标      |     B |     D |                  D − B |
| --------- | ----: | ----: | ----------------------: |
| Exact     | 0.200 | 0.400 |                  +0.200 |
| MAE       | 0.417 | 0.333 | **−0.083，改善** |
| RMSE      | 0.536 | 0.507 |                 −0.029 |
| Threshold | 0.600 | 0.600 |                   0.000 |

在 continuum wording 下，增加到六挡反而有所改善。

因此：

> Resolution effect 的方向取决于 anchor wording。不存在一个可脱离 wording 单独陈述的“5→6 必然变差”效应。

## 5. Wording effect

### 5.1 固定五挡

```text
A → B
5 qualitative → 5 continuum
```

| 指标      |     A |     B |                 B − A |
| --------- | ----: | ----: | ---------------------: |
| Exact     | 0.467 | 0.200 |                −0.267 |
| MAE       | 0.183 | 0.417 | **+0.233，变差** |
| Threshold | 0.933 | 0.600 |                −0.333 |

在五挡下，continuum 明显差于 qualitative。

### 5.2 固定六挡

```text
C → D
6 qualitative → 6 continuum
```

| 指标      |     C |     D |                    D − C |
| --------- | ----: | ----: | ------------------------: |
| Exact     | 0.133 | 0.400 |                    +0.267 |
| MAE       | 0.373 | 0.333 | **−0.040，略改善** |
| Threshold | 0.600 | 0.600 |                     0.000 |

在六挡下，continuum 并未继续造成同方向退化，反而略有改善。

因此：

> Wording effect 的方向同样取决于 resolution。

## 6. Interaction 是主要结果

以 MAE 为例：

```text
wording effect @ 5 = +0.233
wording effect @ 6 = −0.040
interaction         = −0.273
```

以 exact accuracy 为例：

```text
wording effect @ 5 = −0.267
wording effect @ 6 = +0.267
interaction         = +0.533
```

平均主效应：

```text
MAE wording main effect    = +0.0967
MAE resolution main effect = +0.0533
MAE interaction magnitude  =  0.2733
```

interaction 明显大于两个平均主效应。这是典型的 crossover：

```text
qualitative 下：5 比 6 好
continuum 下：  6 比 5 好
```

所以原始 A→D 的退化不能归因为：

```text
resolution alone
```

也不能归因为：

```text
wording alone
```

更准确的结论是：

> 五挡的优势来自 `5-level × qualitative semantic anchors` 这一组合，anchor 数量与表达方式存在强交互。

## 7. 逐 case 解释

### 7.1 五挡 wording effect 主要由 observer/control case 驱动

`att_07d7cc78f5b0` 的 Gold=1。Gold 说明 `wire.jsonl:4` 的 `parse_failed` 是 observer-side capture failure，不是 agent-visible task-operation failure。

```text
A 5 qualitative: 1 / 1 / 1
B 5 continuum:   0 / 0 / 0
```

A 和 B 都检索到了成功 Edit/Read 与 `wire.jsonl:4`。差异不是“B 没找到证据”，而是解释不同：

- A 把 `parse_failed` 正确识别为 capture-layer/derived event，不要求被测 agent 处理；
- B 把同一个 observer-side event 当成 agent-visible explicit failure，并认为未恢复。

该 case 单独贡献了 A→B MAE 增量中的 `+0.20`；A→B 总增量是 `+0.233`。因此五挡 wording effect 的约 86% 来自一个 evidence applicability / interpretation reversal。

这属于 end-to-end wording sensitivity，但不能简单解释为 continuum 数值刻度本身不好。

### 7.2 六挡 qualitative 与 continuum 在不同 case 上互相抵消

C→D 的净 MAE 只改善 `0.04`，但内部并不稳定：

- ignored-failure case：D 比 C 更差；D 三次都给 1.0，而 Gold=0；
- partial-recovery A：C 略好；
- successful recovery：D 更好；
- observer/control：D 明显更好；
- partial-recovery B：两者都稳定错误地给 1.0。

因此 D 相对 C 的小幅优势是多种相反 case effect 抵消后的结果，不代表 continuum 在六挡下普遍更优。

### 7.3 D 的六挡崩溃包含 retrieval/investigation failure

D 在 ignored-failure case 的三轮没有引用 Gold required evidence `trace.jsonl:2`，并被自动标记为 retrieval failure。C 有两轮找到了该明确编译失败并给 0.2，第三轮没有找到证据而给 1.0。

因此原来的 A→D 退化不仅混合 resolution 与 wording，还包含不同 investigation trajectory 造成的 retrieval 差异。

这说明对于 Agentic Judge：

```text
anchor wording
不仅可能影响最后选哪个分数
也可能影响 Judge 搜什么、何时停止、如何解释 applicability
```

## 8. 回答最初问题

### Resolution effect 是否导致 5→6 崩溃？

不能单独成立：

```text
qualitative 下 5→6 变差
continuum 下 5→6 改善
```

### Anchor wording effect 是否导致崩溃？

也不能单独成立：

```text
5 挡下 continuum 变差
6 挡下 continuum 略改善
```

### 最终判断

> 原 A→D 的崩溃主要是一个 `resolution × wording × agent investigation` 的交互现象。当前最可靠的具体配置仍然是 A：五挡 qualitative semantic anchors，但不能把“五挡”抽象成与 wording 无关的普遍最优挡位。

## 9. 可信性限制

1. 只有 5 个定向 case；observer/control 单 case 对结果影响极大。
2. 每格只有 3 repeats。
3. A/D 与 B/C 不是同一时间批次运行，外部模型服务漂移无法完全排除。
4. Meta-eval seed 没有固定外部模型采样随机性。
5. 这是 end-to-end Agentic Judge 消融；wording 可能改变 investigation trajectory，因此不是“固定证据后仅比较 score selector”的纯 scoring-stage 实验。
6. `att_9c539666b31d` 在四格全部给 1.0、Gold=0.5，说明仍有与两个实验因子都无关的系统性推理偏差。

## 10. 可复现产物

```text
run/meta_eval/failure-handling-anchor-wording-ablation-v1/manifest.json
run/meta_eval/failure-handling-anchor-wording-ablation-v1/analysis.json
run/meta_eval/failure-handling-anchor-wording-ablation-v1/5-level-continuum/
run/meta_eval/failure-handling-anchor-wording-ablation-v1/6-level-qualitative/
tools_analyze_anchor_wording_ablation.py
tools_plot_anchor_wording_ablation.py
docs/assets/anchor_wording_2x2_ablation.png
```

离线重放分析：

```bash
.venv/bin/python tools_analyze_anchor_wording_ablation.py
python3 tools_plot_anchor_wording_ablation.py
```

## 11. 后续 frozen-evidence scoring 消融

后续实验已固定相同 evidence facts、claim set、missing facts 与 source applicability，并移除全部 Evidence Tools，仅比较四种 anchor ladder 的 score mapping：

```text
docs/META_EVAL_FROZEN_EVIDENCE_SCORING_ABLATION_2026-08-27.md
```

MAE interaction 从本端到端实验的 `-0.2733` 缩小为 `+0.0467`，绝对保留约 17%，且方向反转。这进一步表明本报告中的强 crossover 主要发生在 Agentic Judge 的 investigation / interpretation loop，而不是纯 scoring stage。

## 12. Anchor-aware Gold 后续校正

Retrieval-only 实验发现旧 numeric Gold 与新增 anchor semantics 冲突。Post-hoc anchor-aware 重分析后：

```text
A MAE: 0.033
B MAE: 0.267
C MAE: 0.213
D MAE: 0.173
MAE interaction: -0.2733
```

MAE crossover interaction 保持不变，因此本报告关于强端到端 interaction 的主结论仍成立。但绝对 MAE/Exact 与部分 case-level failure 归因应以后续报告为准：

```text
docs/META_EVAL_RETRIEVAL_ONLY_ANCHOR_SENSITIVITY_2026-08-27.md
```
