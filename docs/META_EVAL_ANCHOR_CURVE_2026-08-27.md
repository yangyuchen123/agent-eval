# 评分挡位数量曲线（2026-08-27）

## 图 1：当前观测

![评分挡位数量观测曲线](assets/anchor_resolution_observed_curves.png)

图中严格区分了两类数据：

```text
实线：历史 16 Gold、每挡位单次实验
虚线大点：当前 30 Gold、每 case 3 repeats 控制实验
```

两类实验的 Gold 分布和重复次数不同，因此不把它们连接为同一条拟合曲线。

当前观测显示：

- 历史单次 Gold exact accuracy 从 2 到 5 挡总体上升，中间在 3/4 挡持平；没有出现峰值后下降；
- 历史 MAE 总体下降，4 挡比 3 挡略差；更接近尚未出现右侧上升段的 U 型；
- 单 case smoke 的 std 只有 4 挡出现局部峰值，不是随挡位数单调变化；
- 当前严格可比的 30-case 重复实验只有 2 和 5 两个端点，无法确定 3/4 挡的曲线形状；
- 五挡位的每 observation 成本明显高于二挡位。

## 图 2：理论假设

![评分挡位数量理论假设](assets/anchor_resolution_theoretical_hypothesis.png)

如果存在经典偏差–方差权衡：

```text
挡位太少
→ 量化偏差大，partial 状态被强制压成 0/1

挡位适中
→ 表达能力和边界清晰度达到较好平衡

挡位太多
→ 相邻 anchor 边界模糊、Judge 调查和选择方差增加
```

那么不同指标对应的曲线应是：

```text
准确率 / 可信度：倒 U 型（钟形）
总误差 / 风险：U 型
成本：通常随挡位数量上升，不是钟形
```

因此需要先明确纵轴。不能笼统地说“指标理论上都是钟形”。

## 当前不能拟合钟形的原因

真正能验证拐点的实验必须满足：

```text
同一批 30 Gold
同一 Judge/model/config
同一 runtime snapshot
同一 repeats
只改变 2 / 3 / 4 / 5 anchors
```

在完整 30-case 层面，当前严格受控数据只有：

```text
2 levels
5 levels
```

两个端点不能识别：

```text
单调线性
U 型
倒 U 型
平台型
局部非单调
```

历史 3/4 挡位数据可以作为探索性参考，但不能与当前 30-case 结果混合拟合成“证实的钟形”。

## 已完成的 5-case、2–9 挡实验

低成本子集实验已经扩展到 2–9 挡，每挡三次，共 120 个真实 observation。完整结果见：

```text
docs/META_EVAL_ANCHOR_SMALL_TURNING_POINT_2026-08-27.md
```

![5-case 2–9 挡评分分辨率实验](assets/anchor_resolution_small_turning_point.png)

当前结论：

- 五挡在 MAE、RMSE、threshold agreement 和 evidence overlap 上为观测最佳；
- 4→5 改善、5→6 恶化，形成一个多指标候选局部拐点；
- 6–9 挡继续明显震荡，不构成平滑钟形；
- 六挡虽然重复方差最低，但在明确失败 case 上三次稳定误判，说明低方差不等于可靠；
- 九挡出现一次 922k input-token 的 evidence-navigation 尾部成本异常；
- 五挡拐点仍只适用于当前 5-case、单 question 探索集，不能视为总体最优值。

## 结论

> 2–9 挡实验已经观察到五挡附近的多指标局部拐点，但没有观察到平滑、对称的钟形曲线。当前更准确的描述是“五挡局部最优，六挡后进入高噪声非单调区域”。下一步应扩大困难 Gold case，而不是继续增加挡位来追求更漂亮的曲线。


## 2×2 wording 消融后的解释更新

五挡与六挡已经完成 qualitative/continuum 交叉消融。结果显示强 crossover interaction，详见：

```text
docs/META_EVAL_ANCHOR_WORDING_2X2_ABLATION_2026-08-27.md
```

因此曲线中的五挡局部最佳点不能继续解释为纯 resolution effect。更准确的表述是：

```text
5-level qualitative 是当前最佳组合；
挡位数量的效应依赖 anchor wording；
wording 也会改变 Agent Judge 的 investigation trajectory。
```
