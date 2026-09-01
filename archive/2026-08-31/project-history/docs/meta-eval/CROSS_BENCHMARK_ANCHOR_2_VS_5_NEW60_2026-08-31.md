# 新 60 条跨 Benchmark Gold：2 档 vs 5 档 Judge 对比

日期：2026-08-31。

本实验重新使用当前冻结的 60 条新数据：HealthBench 20、RuVerBench DeepResearch 20、RuVerBench AgenticCoding 20。两种条件只改变 `score_anchors` 档位数量，case、response/trajectory、rubric、Gold、model 和 Judge service 保持不变；没有运行 Harbor/Pi。每个条件 60 次单次 Judge replay。

| 指标 | 2 档 | 5 档 | 5 档 - 2 档 |
|---|---:|---:|---:|
| Binary accuracy | 68.3% | 75.0% | +6.7% |
| Balanced accuracy | 66.5% | 75.3% | +8.8% |
| Positive F1 | 0.5778 | 0.7368 | +0.1591 |
| Gold MAE | 0.3278 | 0.2708 | -0.0569 |
| Scored | 60/60 | 60/60 | |
| Execution errors | 0 | 0 | |

| Benchmark | 2 档 Acc | 5 档 Acc | 2 档 MAE | 5 档 MAE |
|---|---:|---:|---:|---:|
| HealthBench | 60.0% | 70.0% | 0.4333 | 0.3250 |
| RuVer DeepResearch | 80.0% | 75.0% | 0.2000 | 0.2500 |
| RuVer AgenticCoding | 65.0% | 80.0% | 0.3500 | 0.2375 |

## 结果

2 档 accuracy 为 **68.33% (41/60)**；5 档为 **75.00% (45/60)**。Balanced accuracy 从 66.50% 提升到 75.25%，正类 F1 从 0.5778 提升到 0.7368，Gold MAE 从 0.3278 降到 0.2708。

如果目标是相信现有 Gold，并最大化与 Gold 的二元一致性，本次新实验不支持将 5 档替换成 2 档。

分 domain：HealthBench 60%→70%，DeepResearch 80%→75%，AgenticCoding 65%→80%。因此 2 档仅在 DeepResearch 这组 point-level 样本上胜出。

## 边界

每个 case 每个条件只运行 1 次，尚未测 repeat consistency 或 perturbation stability。AgenticCoding trajectory 仍按当前 pilot 的序列化方式提供，不是结构化 EvidenceProvider replay。三个 benchmark 的 Gold 语义不同，结果不能解释为 AgentEval 全局准确率。

## 建议

暂不覆盖生产 rubric；先固定 60 条做每条件 3 次重复，确认 5 档优势是否稳定。二档仍可作为明确 binary checklist 的低成本专用协议，但不宜作为当前跨域统一协议。
