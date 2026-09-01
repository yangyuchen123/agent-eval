# 5-case、2–9 挡评分分辨率实验（2026-08-27）

## 1. 实验问题

本实验验证：

> 对同一个细粒度 rubric question，离散评分 anchor 从 2 增加到 9 时，Judge 的 Gold 一致性、连续误差、重复稳定性、证据一致性和成本如何变化？是否出现可观察的可靠性拐点？

冻结条件：

```text
question_id = observed_failure_handling
judge_mode = agentic_evidence
model = gpt-5.6-luna
repeats = 3
perturbation = none
seeds = 20260825 / 20260826 / 20260827
```

程序校验确认：

- 2–9 挡使用同一个 Judge model；
- 每个挡位使用相同的三个 seed；
- 每个 case 在所有挡位中的 trace digest 完全相同；
- 没有修改 EvidenceCatalog；
- 没有增加 mandatory query、question-specific retrieval 或 deterministic score policy；
- 6–9 挡没有使用 case-specific anchor 描述。

## 2. Gold 子集

| Case                 | Gold | 类型                                       |
| -------------------- | ---: | ------------------------------------------ |
| `att_fa8655f8ce1d` |  0.0 | explicit failure ignored                   |
| `att_8ca4f9ec3ba9` |  0.5 | partial recovery A                         |
| `att_9c539666b31d` |  0.5 | partial recovery B；历史上倾向被过度给满分 |
| `att_a1bb35bb6955` |  1.0 | successful recovery                        |
| `att_07d7cc78f5b0` |  1.0 | observer/N-A control                       |

Gold 分布：

```text
0.0: 1 case  (20%)
0.5: 2 cases (40%)
1.0: 2 cases (40%)
```

这是有意选择的高信息量探索子集，不是从 30-case Gold 中随机抽样。

## 3. 实验规模与成本

```text
5 cases × 8 anchor counts × 3 repeats
= 120 observations
```

其中：

- 2、5 挡复用已有结果；
- 3、4 挡来自前一轮补点；
- 6、7、8、9 挡本轮新增 60 个真实 Judge observation；
- 本轮 6–9 挡记录的 provider cost 合计为 `0.6994008`；
- 2–9 挡全部 120 observations 的记录 cost 合计为 `1.0873894`。

## 4. Anchor 构造

2–5 挡沿用已经冻结并实际运行过的定义：

```text
2: 0 / 1
3: 0 / 0.5 / 1
4: 0 / 1/3 / 2/3 / 1
5: 0 / 0.25 / 0.5 / 0.75 / 1
```

6–9 挡使用一个统一、case-neutral 的生成器：

```text
score_i = i / (levels - 1)
```

所有中间档使用相同的 dimension-level continuum 模板，只替换完成百分比。端点继续保持 `unsupported` 与 `supported` 的原始语义。

实现：

```text
build_resolution_rubric(levels)
```

### 控制变量限制

6–9 挡的中间 anchor 使用统一百分比 continuum 描述，而 2–5 挡使用此前冻结的定性描述。因此：

> 5→6 的变化同时包含“anchor 数量增加”和“中间 anchor 表述由定性档位切换为统一 continuum 模板”。

这不是 case-specific prompt 调优，但仍然是一个实验构造差异。因此下面把 5 挡称为**候选局部拐点**，而不是已经证明由 anchor 数量单独导致的因果最优点。

## 5. 总体曲线

![2–9 挡评分分辨率曲线](assets/anchor_resolution_small_turning_point.png)

|        挡位 |        Exact ↑ |          MAE ↓ |         RMSE ↓ |    Threshold ↑ | Stable cases ↑ |     Mean std ↓ | Evidence Jaccard ↑ |     Mean cost/obs |   Median cost/obs |
| ----------: | --------------: | --------------: | --------------: | --------------: | --------------: | --------------: | ------------------: | ----------------: | ----------------: |
|           2 | **0.533** |           0.267 |           0.408 |           0.733 |   **4/5** |           0.115 |               0.734 |           0.00541 | **0.00315** |
|           3 |           0.400 |           0.333 |           0.447 |           0.667 |             2/5 |           0.215 |               0.739 |           0.00619 |           0.00325 |
|           4 |           0.333 |           0.311 |           0.451 |           0.667 |             3/5 |           0.192 |               0.591 |           0.00608 |           0.00381 |
| **5** |           0.467 | **0.183** | **0.266** | **0.933** |   **4/5** |           0.050 |     **0.760** |           0.00818 |           0.00471 |
|           6 |           0.400 |           0.333 |           0.507 |           0.600 |   **4/5** | **0.023** |               0.680 |           0.00626 |           0.00350 |
|           7 |           0.400 |           0.222 |           0.304 |           0.867 |   **4/5** |           0.067 |               0.699 |           0.00623 |           0.00395 |
|           8 |           0.400 |           0.305 |           0.429 |           0.667 |             3/5 |           0.109 |               0.576 | **0.00580** |           0.00409 |
|           9 |           0.400 |           0.258 |           0.378 |           0.800 |             2/5 |           0.159 |               0.701 |           0.02834 |           0.00436 |

粗体只是各列的观测最优值，不表示统计显著。

## 6. 是否出现拐点？

### 6.1 五挡形成了清晰的多指标局部极值

相邻三点：

| 指标                     |  4 挡 |            5 挡 |  6 挡 | 五挡形态 |
| ------------------------ | ----: | --------------: | ----: | -------- |
| Strict exact accuracy ↑ | 0.333 | **0.467** | 0.400 | 局部峰值 |
| MAE ↓                   | 0.311 | **0.183** | 0.333 | 局部谷值 |
| RMSE ↓                  | 0.451 | **0.266** | 0.507 | 局部谷值 |
| Threshold agreement ↑   | 0.667 | **0.933** | 0.600 | 局部峰值 |
| Evidence Jaccard ↑      | 0.591 | **0.760** | 0.680 | 局部峰值 |

因此可以说：

> 在这个 5-case 探索集上，五挡是目前第一个同时被 Gold 连续误差、threshold agreement 和证据重叠支持的候选局部拐点。

这比只有 2–5 挡时的结论更强，因为现在已经实际观察到 5→6 的右侧退化。

### 6.2 但整条曲线不是平滑钟形

例如 threshold agreement：

```text
0.733 → 0.667 → 0.667 → 0.933 → 0.600 → 0.867 → 0.667 → 0.800
```

MAE：

```text
0.267 → 0.333 → 0.311 → 0.183 → 0.333 → 0.222 → 0.305 → 0.258
```

6–9 挡出现反复震荡，而不是从五挡之后单调恶化。因此当前数据更像：

```text
局部最优 + 高方差非单调区域
```

而不是：

```text
平滑、对称、可直接拟合的钟形曲线
```

不应为了图形美观对 8 个离散点强行拟合高斯曲线。

## 7. 五挡局部优势由哪些 case 驱动？

### 7.1 5→6 的 MAE 恶化主要由一个明确失败 case 驱动

`att_fa8655f8ce1d` 的人工 Gold 是 0：

```text
5 挡：0.25 / 0.25 / 0.25
6 挡：1.00 / 1.00 / 1.00
```

该 case 的平均绝对误差从 `0.25` 上升到 `1.0`。它单独贡献了总体 MAE 的全部 `+0.15` 增量：

```text
5 挡 MAE 0.183
6 挡 MAE 0.333
```

因此五挡局部谷值虽然真实存在于当前 observations，但对单个 case 非常敏感。

### 7.2 Partial recovery A 在五挡表达最好

`att_8ca4f9ec3ba9`，Gold=0.5：

```text
2: mean 0.000
3: mean 0.167
4: mean 0.333
5: mean 0.500
6: mean 0.333
7: mean 0.333
8: mean 0.143
9: mean 0.333
```

五挡是唯一均值精确落到 Gold 的 condition。

### 7.3 Partial recovery B 暴露出与挡位数无关的稳定偏差

`att_9c539666b31d` 在 2–9 挡的所有 24 个 observation 中都输出：

```text
1.0
```

人工 Gold 是 `0.5`。这表明该错误不是量化分辨率不足，而更可能属于 evidence interpretation、rubric anchor application 或 reasoning failure。

### 7.4 低方差不等于可靠

六挡的 mean per-case std 最低：

```text
0.023
```

但其 MAE 和 RMSE 很差。原因之一正是明确失败 case 被三次稳定地误判为 `1.0`。

所以不能把：

```text
score variance 越低
```

直接等价为：

```text
Judge 越可信
```

## 8. 九挡成本异常

九挡平均 cost/observation 为 `0.02834`，看起来远高于其他挡位。但其中一个 observation：

```text
case: att_8ca4f9ec3ba9
seed: 20260827
input tokens: 922,129
cost: 0.33745328
```

该轮 Judge 调用了 generic `get_related_evidence(after)`，返回了数千个 `events.jsonl` 记录，形成一次超长 investigation。

去掉该单次异常，仅用于诊断而不修改正式结果：

```text
其余 14 observations 总成本：0.08759208
其余 14 observations 平均成本：0.00625658
九挡正式中位数成本：0.00435816
```

因此：

- 九挡的**典型成本**没有比五挡高一个数量级；
- 九挡暴露的是 agentic investigation 的尾部成本风险；
- 该异常不能简单归因为 anchor 数量，因为直接原因是一次过宽的 related-evidence navigation；
- 正式统计必须保留该异常，不能为了曲线好看删除。

## 9. 当前结论

### 可以说

1. 在这个 5-case、单 question 的探索实验中，五挡是 MAE、RMSE、threshold agreement 和 evidence overlap 的观测最佳点。
2. 4→5 改善、5→6 恶化构成一个明确的**多指标候选局部拐点**。
3. 更高挡位没有持续带来更低误差；6–9 挡进入明显的非单调波动区。
4. “挡位越多，方差必然越大”仍然不成立；六挡方差最低，却稳定地犯了严重错误。
5. 九挡暴露出一次真实的长调查成本异常。

### 还不能说

1. 不能说总体最优挡位已经被统计证明为 5。
2. 不能说完整曲线是平滑钟形或倒 U 型。
3. 不能把结果外推到其他 rubric question。
4. 不能把 5→6 的全部变化因果归于 anchor 数量，因为 6–9 使用了统一 continuum 中间描述。
5. 不能从 5 个定向选择的 case 推断 30-case 总体效果。

## 10. 下一步最有信息增益的验证

若后续继续验证，不应立即增加到 10、11、12 挡。最高信息增益是：

```text
在更多 Gold=0 与 Gold=0.5 case 上
复核 5 挡 vs 6 挡
```

原因是当前五挡局部优势主要由困难 case 驱动。扩大 case 多样性比继续横向增加挡位更能判断五挡拐点是否泛化。

## 11. 可复现产物

```text
run/meta_eval/failure-handling-anchor-small-v1/manifest.json
run/meta_eval/failure-handling-anchor-small-v1/curve-analysis.json
run/meta_eval/failure-handling-anchor-small-v1/{3,4,6,7,8,9}-levels/
tools_analyze_small_anchor_curve.py
tools_plot_small_anchor_turning_point.py
docs/assets/anchor_resolution_small_turning_point.png
```

离线重新分析并绘图：

```bash
.venv/bin/python tools_analyze_small_anchor_curve.py
python3 tools_plot_small_anchor_turning_point.py
```

上述命令只读取保存的实验记录，不调用 Judge API。


## 12. 后续 2×2 wording 消融更新

后续已经补齐：

```text
5-level qualitative / continuum
6-level qualitative / continuum
```

结果见：

```text
docs/META_EVAL_ANCHOR_WORDING_2X2_ABLATION_2026-08-27.md
```

消融显示强 crossover interaction：

```text
qualitative 下：5→6 MAE +0.190，变差
continuum 下：  5→6 MAE −0.083，改善

5 挡下：qualitative→continuum MAE +0.233，变差
6 挡下：qualitative→continuum MAE −0.040，略改善
```

因此本文中的“五挡候选局部拐点”应收紧为：

> 当前观测最佳的是 `5-level qualitative semantic anchors` 这个具体组合，不是已经证明与 wording 无关的纯五挡 resolution 最优点。
