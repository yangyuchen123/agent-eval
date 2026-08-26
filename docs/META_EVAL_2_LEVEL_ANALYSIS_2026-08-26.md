# 2 挡位实验分析（2026-08-26）

## 实验对象

本次实际运行的是：

```text
question: observed_failure_handling
judge mode: agentic_evidence
model: gpt-5.6-luna
Gold cases: 30
repeats: 3
perturbation: none
anchors: 0 / 1
```

控制变量保持为同一批人工 Gold、同一 runtime snapshot、同一 EvidenceCatalog、同一模型配置和同一 Judge 实现。5 挡位实验已在启动阶段停止，没有有效结果，因此本文件只分析 2 挡位，并与之前的 2/3/4/5 挡位单次实验和早期 smoke 实验作谨慎比较。

原始结果：

```text
run/meta_eval/failure-handling-anchor-v2-v5/2-levels/
```

## 当前 30 Gold × 3 repeats 结果

### 分数与人工 Gold

```text
总 observation: 90
有效分数: 87
Judge error / unavailable: 3
```

有效分数分布：

```text
Judge = 0: 36
Judge = 1: 51
```

严格按人工 Gold 的离散值精确匹配：

```text
46 / 90 = 51.11%    # 将 unavailable 计为未命中
46 / 87 = 52.87%    # 只在有效分数上计算
```

可复现计算出的平均绝对误差：

```text
MAE = 0.3333
```

这里的 MAE 直接使用人工 Gold 的 `0 / 0.5 / 1` 与二挡位输出 `0 / 1` 比较，因此二挡位对所有 Gold=0.5 的 partial case 至少会产生 0.5 的量化误差；这不是 Judge reasoning 错误，而是二值 anchor 的表达能力限制。

如果只看二值化后的“是否达到 0.5”阈值：

```text
threshold agreement = 58.62%（51 / 87 有效输出）
```

但该指标不能替代原始 Gold exact match，因为它会隐藏 `0.5` partial 与 `1.0` fully recovered 之间的区别。

### 重复稳定性

30 个 case 中：

```text
24 / 30 个 case 的 3 次分数完全一致
24 / 30 个 case 的 3 次 status 完全一致
29 / 30 个 case 获得了 3 次有效分数
```

其余 6 个 case 出现重复间波动或 Judge error。有效输出的平均 per-case score std 约为：

```text
0.1195
```

重要的是，稳定性并不等于准确性。部分 case 每次都稳定地输出了错误 anchor，例如：

```text
Gold = 0.5，但三次都输出 0
Gold = 0.5，但三次都输出 1
Gold = 1，但三次都输出 0
```

### 错误结构

90 次 observation 的 Gold / prediction 交叉统计为：

```text
Gold 1.0 → Judge 1.0: 43
Gold 1.0 → Judge 0.0: 14
Gold 1.0 → unavailable: 3
Gold 0.5 → Judge 0.0: 19
Gold 0.5 → Judge 1.0: 5
Gold 0.0 → Judge 0.0: 3
Gold 0.0 → Judge 1.0: 3
```

因此当前二挡位的主要问题不是简单的随机漂移，而是：

1. **无法表达 partial recovery**：24 个 partial-case observation 中，19 次被压到 0，5 次被抬到 1；
2. **存在明确的过度否定**：14 次 Gold=1 被判为 0；
3. **仍存在少量过度肯定**：3 次 Gold=0 被判为 1；
4. **有 3 次 Judge 不可用**。

## 与之前结果的比较

### 与之前 16 Gold、单次 2 挡位实验比较

之前的实验：

```text
16 个 Gold
每个条件 1 次
2 anchors: 0 / 1
```

结果：

```text
strict exact accuracy: 56.25%
available-only accuracy: 60.00%
MAE: 0.4000
```

本次结果：

```text
30 个 Gold × 3 repeats
strict exact accuracy: 51.11%
available-only accuracy: 52.87%
MAE: 0.3333
```

不能简单解读为“本次准确率下降”或“本次 MAE 改善”，原因是两次实验不是同一批样本：

- 之前 16 个 Gold 几乎全是 `1.0`，没有 partial Gold；
- 本次增加了 8 个 `0.5` partial Gold、2 个 `0.0` ignored Gold 和更多不同类型样本；
- 本次还做了 3 次重复，统计单位从 16 次变成 90 次。

可作出的可靠比较是：

> 扩充 Gold 后，二挡位的 MAE 从 0.4000 变为 0.3333，但 exact agreement 只有约 51%–53%。这说明二挡位的误差不仅来自随机性，也来自对中间状态的结构性量化损失。

### 与之前 3/4/5 挡位、16 Gold、单次实验比较

早期同批 16 Gold 的结果为：

| 挡位 | strict exact accuracy | available-only accuracy | MAE |
|---:|---:|---:|---:|
| 2 | 56.25% | 60.00% | 0.4000 |
| 3 | 62.50% | 66.67% | 0.2667 |
| 4 | 62.50% | 62.50% | 0.2708 |
| 5 | 68.75% | 73.33% | 0.2167 |

这组结果支持一个局部结论：在那 16 个 Gold、每个条件只运行一次的实验中，二挡位误差最大，五挡位误差最小。

但它不能证明五挡位普遍更准，也不能用来证明挡位越多方差越大。因为：

- 早期 16 Gold 没有 partial Gold，无法测量中间 anchor 是否真的有帮助；
- 5 挡位在这次 30 Gold 上没有完成重复实验；
- 2 挡位当前重复实验显示，二挡位可以在错误答案上保持稳定。

### 与早期 smoke stability 实验

之前同一个 smoke case 的结果显示：

```text
2 levels: std = 0
3 levels: std = 0
4 levels: std ≈ 0.038
5 levels: std = 0
```

当前 30 Gold 的 2 挡位结果则显示：

```text
24 / 30 case exact score agreement
mean per-case std ≈ 0.1195
```

这两个结果并不矛盾：smoke case 只代表一个特定输入；扩充到真实多样 Gold 后，二挡位也会出现显著 case-level 波动。由此不能再把单个 smoke case 的 `std=0` 泛化为二挡位整体稳定。

## 当前结论

### 可以确认

1. **二挡位不是可靠的细粒度评分方案。** 它无法区分人工标注的 partial recovery，导致结构性误差。
2. **二挡位在部分 case 上具有重复稳定性，但稳定地错误。** 24/30 case 的重复输出一致，不等价于 24/30 case 判断正确。
3. **二挡位的主要损失是分辨率损失，而不只是随机波动。** 24 个 partial-case observation 中大多数被直接压到 0。
4. **扩充 Gold 后，二挡位的表现更接近真实困难度。** 早期 16 case 的结果偏乐观，因为几乎没有中间状态。
5. **不能从现有数据推出“挡位越多，方差越大”。** 已有实验中 4 挡位曾出现局部波动，但 5 挡位 smoke 并没有表现出更大方差。

### 不能确认

目前不能根据已完成数据确认：

```text
5 挡位在当前 30 Gold 上是否优于 2 挡位
5 挡位在相同 3 次重复下的稳定性
5 挡位是否能够正确区分 partial recovery
```

因为 5 挡位实验已停止，目录中只有 manifest，没有有效 judgments 或 metrics。

## 建议的工程决策

当前建议：

```text
2 levels：保留为二值 baseline，不作为默认生产评分
3 levels：继续作为当前稳健基线
5 levels：保留为实验候选，暂不因早期 16-case 单次结果直接切换
```

如果后续要控制成本，不必再对 30 个 case 全量运行 5 挡位。可以选择一个有代表性的低成本子集，例如：

```text
8 个 case：2 个明确成功、2 个明确失败、3 个 partial、1 个 N/A
每挡 3 repeats
```

但在当前用户要求下，本轮不再发起新的外部 Judge 调用。

## 成本

2 挡位完整实验记录的 usage metadata 汇总为：

```text
约 1.03978072
4,959,023 input tokens
61,145 output tokens
263 requests
235 evidence tool calls
```

如果 endpoint 的 cost 单位是美元，则本轮成本约为 `$1.04`。5 挡位没有产生有效评测成本。
