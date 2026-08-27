# 2 挡位与 5 挡位真实重复实验对比（2026-08-27）

## 实验设计

本次完成了严格控制变量的 2/5 挡位比较：

```text
Gold cases: 30
question: observed_failure_handling
repeats per case: 3
judge mode: agentic_evidence
model: gpt-5.6-luna
perturbation: none
```

两组共享同一批 case、人工 Gold、runtime snapshot、EvidenceCatalog、Judge 实现、模型配置和 repeat seeds。唯一变化是离散评分锚点：

```text
2 levels: 0 / 1
5 levels: 0 / 0.25 / 0.5 / 0.75 / 1
```

原始产物：

```text
run/meta_eval/failure-handling-anchor-v2-v5/2-levels/
run/meta_eval/failure-handling-anchor-v2-v5/5-levels/
run/meta_eval/failure-handling-anchor-v2-v5/2-vs-5-comparison.json
```

## 核心结果

| 指标 | 2 挡位 | 5 挡位 | 观察 |
|---|---:|---:|---|
| observations | 90 | 90 | 相同 |
| available | 87 | 89 | 5 挡位少 2 次不可用 |
| coverage | 96.67% | 98.89% | 5 挡位更高 |
| strict exact Gold accuracy | 51.11% | 51.11% | 完全相同，均为 46/90 |
| available-only exact accuracy | 52.87% | 51.69% | 2 挡位略高 |
| MAE | 0.3333 | 0.2079 | 5 挡位降低约 37.6% |
| threshold agreement | 58.62% | 78.65% | 5 挡位明显更高 |
| exact-score stable cases | 24/30 | 20/30 | 5 挡位更多 case 在相邻 anchor 间波动 |
| mean per-case std | 0.1195 | 0.0790 | 5 挡位波动幅度反而更小 |
| exact-status stable cases | 24/30 | 22/30 | 2 挡位略高 |

## 最重要的解释

### 1. 五挡位没有提高 exact accuracy，但显著降低了误差距离

两个条件严格 exact accuracy 都是：

```text
46 / 90 = 51.11%
```

但 MAE 从：

```text
2 levels: 0.3333
5 levels: 0.2079
```

下降约 37.6%。原因是五挡位经常输出 `0.25` 或 `0.75`。这些结果不一定精确等于人工 Gold 的 `0 / 0.5 / 1`，所以 exact accuracy 不增加；但它们通常比二挡位被迫输出的 0 或 1 更接近 Gold。

因此五挡位的优势是：

> **更好的连续校准和误差距离，而不是更高的精确分类命中率。**

### 2. 五挡位更能表达 partial，但只很少精确选择 0.5

人工 Gold=0.5 的 observation：

#### 2 挡位

```text
0.0: 19
1.0: 5
exact 0.5: 0
MAE: 0.5000
```

#### 5 挡位

```text
0.25: 8
0.50: 2
0.75: 10
1.00: 3
unavailable: 1
MAE: 0.2609
```

五挡位把 partial case 从强制二值化变成了“有限恢复 / 部分恢复 / 大部分恢复”判断，所以 MAE 大幅下降。但是，23 个有效 partial observation 中只有 2 个精确选择了 0.5。

这说明当前 Judge 更倾向于把人工定义的 partial 拆成：

```text
0.25 limited recovery
0.75 substantial recovery
```

它可能提供了更细信息，也可能表示五挡位 anchor 与人工三挡 Gold 的语义边界仍不一致。不能仅凭 MAE 下降认定这些细分都正确。

### 3. 五挡位没有支持“挡位越多，出分方差越大”的简单结论

五挡位完全一致的 case 数量下降：

```text
2 levels: 24 / 30
5 levels: 20 / 30
```

但平均 per-case std 同时下降：

```text
2 levels: 0.1195
5 levels: 0.0790
```

原因是二挡位一旦波动，就是 `0 ↔ 1` 的整档跳变，单 case std 可达到约 0.577；五挡位虽然更容易在相邻 anchor 间切换，但通常是：

```text
0.25 ↔ 0.75
0.75 ↔ 1.0
```

因此最准确的结论是：

> 五挡位增加了“是否完全一致”的边界波动频率，但减少了平均分数跳变幅度。挡位数量与方差不存在简单单调关系。

### 4. 五挡位改善了 Gold=1 的误差距离，但没有解决所有推理错误

Gold=1 的有效 observation：

```text
2 levels exact: 75.44%, MAE: 0.2456
5 levels exact: 73.33%, MAE: 0.1500
```

五挡位 exact accuracy 略低，但当 Judge 不愿给满分时，能够使用 0.75，而不必直接降到 0，因此 MAE 更低。

仍有一些 Gold=1 case 被稳定判为很低分。例如部分 case 三次稳定输出 0.25，说明问题不是随机性，而是 rubric applicability、evidence interpretation 或人工 Gold/Judge 边界不一致。

### 5. 五挡位在明确失败 Gold 上表现没有改善

Gold=0 只有 2 个 case、6 个 observation，样本很少：

```text
2 levels exact: 50.00%, MAE: 0.5000
5 levels exact: 0.00%, MAE: 0.5833
```

五挡位对这 6 次输出为：

```text
0.25: 3
0.75: 1
1.00: 2
```

没有一次精确输出 0。这意味着当前五挡位可能更倾向给“有限处理”而不是“明确忽略”。但由于 Gold=0 只有 2 个 case，不能据此泛化；它明确提示下一步应审计这两个 case 的 evidence chain，而不是立刻修改 prompt。

## Failure taxonomy

| failure | 2 挡位 | 5 挡位 |
|---|---:|---:|
| R12 stochastic_instability | 14 | 22 |
| R1 retrieval_failure | 4 | 3 |
| R2 evidence_selection_failure | 4 | 2 |
| R6 missing_evidence_failure | 11 | 8 |
| R10 reasoning_failure | 8 | 8 |
| unclassified | 3 | 1 |

五挡位的 retrieval、selection、missing-evidence 和 unclassified 数量有所下降，但 `R10 reasoning_failure` 没有下降，`R12` 增加。这里的 R12 更接近“不完全一致次数”，与平均波动幅度不是同一个统计量。

## 成本和效率

| 指标 | 2 挡位 | 5 挡位 | 五挡位增幅 |
|---|---:|---:|---:|
| cost | 1.0398 | 1.7488 | +68.2% |
| input tokens | 4,959,023 | 7,070,984 | +42.6% |
| output tokens | 61,145 | 73,806 | +20.7% |
| model requests | 263 | 302 | +14.8% |
| evidence tool calls | 235 | 306 | +30.2% |
| mean latency / observation | 20.72s | 23.39s | +12.9% |

如果 endpoint 的 cost 单位是美元，则五挡位本轮约 `$1.75`，比二挡位约多 `$0.71`。

成本主要被少数超长 trace 拉高。五挡位中较昂贵的 case 包括：

```text
att_f7830b42a3d8 ≈ 0.4767
att_2873da6c9103 ≈ 0.2945
att_35f7ed7f3d24 ≈ 0.2481
att_006e3923fb8c ≈ 0.1984
```

这说明之后降低成本的优先方向不是减少 anchor，而是控制超长 trace 的 evidence investigation token 消耗，同时保持 Judge 自主搜索边界。

## 与之前单次 16-Gold 实验的关系

之前的 16-case 单次实验显示：

```text
2 levels MAE: 0.4000
5 levels MAE: 0.2167
```

本次 30-case、3-repeat 结果为：

```text
2 levels MAE: 0.3333
5 levels MAE: 0.2079
```

因此“五挡位降低 MAE”在扩充 Gold 和重复运行后仍然存在。但之前观察到的五挡位 exact accuracy 优势没有保留：本次两者 strict exact accuracy 完全相同。

这使结论更清晰：

```text
五挡位的可靠优势：降低量化误差距离
尚未证明的优势：提高精确 Gold 分类准确率
明确代价：成本、工具调用和边界波动频率上升
```

## 当前决策建议

### 不建议使用二挡位作为生产评分

二挡位只能作为 baseline，因为它对 partial recovery 存在不可避免的表达损失。

### 暂不直接把五挡位升级为默认生产版本

五挡位 MAE 和 threshold agreement 明显更好，但：

- exact Gold accuracy 没有改善；
- 只在 2/30 case 的 Gold=0.5 observation 中精确选择 0.5；
- Gold=0 的两个 case 全部没有选择 0；
- 成本增加约 68%；
- exact-score stability case 数从 24 降到 20。

### 三挡位仍应作为默认基线

当前人工 Gold 本身就是 `0 / 0.5 / 1`，三挡位与 Gold 标签空间天然一致。下一步最有信息价值的实验不是继续增加挡位，而是选择一个成本受控的代表性子集，对三挡位进行 3 次重复，并与当前五挡位结果比较：

```text
Gold exact accuracy
MAE
partial-case accuracy
ignored-failure accuracy
per-case stability
cost
```

## 最终结论

> 五挡位相较二挡位显著降低了 MAE，并提高了阈值判断一致性，证明增加中间锚点可以减少二值化损失；但它没有提高严格 Gold exact accuracy，反而增加了相邻 anchor 之间的不一致频率和约 68% 的成本。因此当前数据支持“二挡位过粗”，但还不足以支持“应直接采用五挡位作为生产默认”。

## 可视化

观测曲线与独立的理论偏差–方差假设图见：

```text
docs/META_EVAL_ANCHOR_CURVE_2026-08-27.md
docs/assets/anchor_resolution_observed_curves.png
docs/assets/anchor_resolution_theoretical_hypothesis.png
```
