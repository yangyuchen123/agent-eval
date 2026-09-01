# 新 60 条 Gold：2 档 vs 5 档 Paired Transition 分析

日期：2026-08-31。基于同一批冻结 case 在 2 档和 5 档条件下的两次单次 replay；不重新调用 Judge。本报告先分析净提升来自哪些 case，而不是先做 repeats。

## 1. Transition matrix

| | 5 档正确 | 5 档错误 | 合计 |
|---|---:|---:|---:|
| 2 档正确 | 36 | 5 | 41 |
| 2 档错误 | 9 | 10 | 19 |
| 合计 | 45 | 15 | 60 |

关键 paired 数量：

- `C = 2 档错误 → 5 档正确 = 9`；
- `B = 2 档正确 → 5 档错误 = 5`；
- 净提升 `C-B = 4`，对应 accuracy 从 41/60 到 45/60。

在不作多重比较校正的前提下，基于 discordant pairs 的 McNemar exact two-sided p 值约为 **0.424**（B=5、C=9）。这说明当前 60 条的 +4 净提升是有方向的描述性结果，但还不足以声称统计显著。

## 2. `2 档错 → 5 档对`（C=9）

### C1. `healthbench_a8bc70f3-6e34-4bde-9b6f-4e6946c0584b_dd2c4c67-e1e6-4d38-a6c2-4050c615bc2a`

- benchmark：HealthBench；category：`communication`；provisional semantic type：`graded_quality_or_safety`
- Gold：`1.0` / binary=`True`
- 2 档 score：`0.0`（错误）；5 档 score：`0.5`（正确）
- point/check：`None`

### C2. `healthbench_ffe00b21-0aff-4b92-b25c-b006b4103d11_35319001-feb4-458b-bc02-b017312ad692`

- benchmark：HealthBench；category：`communication`；provisional semantic type：`graded_quality_or_safety`
- Gold：`1.0` / binary=`True`
- 2 档 score：`0.0`（错误）；5 档 score：`0.5`（正确）
- point/check：`None`

### C3. `healthbench_9a999c02-b265-44e9-8de7-5a01bba98dd2_8ebd9f55-20cb-49d6-853d-017b5d31abf1`

- benchmark：HealthBench；category：`complex_responses`；provisional semantic type：`graded_quality_or_safety`
- Gold：`1.0` / binary=`True`
- 2 档 score：`0.0`（错误）；5 档 score：`0.5`（正确）
- point/check：`None`

### C4. `ruverbench_DRB2_35_8`

- benchmark：RuVer DeepResearch；category：`format`；provisional semantic type：`binary_coverage_or_existence`
- Gold：`1.0` / binary=`True`
- 2 档 score：`0.0`（错误）；5 档 score：`0.5`（正确）
- point/check：`DRB2_35::8`

### C5. `ruverbench_DRB2_29_2`

- benchmark：RuVer DeepResearch；category：`numbers`；provisional semantic type：`factual_numeric_verification`
- Gold：`1.0` / binary=`True`
- 2 档 score：`0.0`（错误）；5 档 score：`0.75`（正确）
- point/check：`DRB2_29::2`

### C6. `ruverbench_DRB2_118_2`

- benchmark：RuVer DeepResearch；category：`facts`；provisional semantic type：`factual_claim_verification`
- Gold：`1.0` / binary=`True`
- 2 档 score：`0.0`（错误）；5 档 score：`0.5`（正确）
- point/check：`DRB2_118::2`

### C7. `ruverbench_coding_md-spy-error-types_ToolSchema_parallel_calls_when_independent`

- benchmark：RuVer AgenticCoding；category：`tools`；provisional semantic type：`binary_protocol_or_event_check`
- Gold：`0.0` / binary=`False`
- 2 档 score：`1.0`（错误）；5 档 score：`0.0`（正确）
- point/check：`ToolSchema_parallel_calls_when_independent`

### C8. `ruverbench_coding_benchmark-bm_checklist_search_001_ToolSchema_write_after_read_when_existing`

- benchmark：RuVer AgenticCoding；category：`tools`；provisional semantic type：`binary_protocol_or_event_check`
- Gold：`1.0` / binary=`True`
- 2 档 score：`0.0`（错误）；5 档 score：`1.0`（正确）
- point/check：`ToolSchema_write_after_read_when_existing`

### C9. `ruverbench_coding_benchmark-bm_append_normalize_001_SP_use_task_tool_for_explore`

- benchmark：RuVer AgenticCoding；category：`rules`；provisional semantic type：`binary_protocol_or_event_check`
- Gold：`1.0` / binary=`True`
- 2 档 score：`0.0`（错误）；5 档 score：`0.5`（正确）
- point/check：`SP_use_task_tool_for_explore`

C 组中 9 条里有 8 条 Gold 为 positive；其中多条 5 档给出 0.5 或 0.75，说明表面上符合“中间 anchor 让 Judge 不再直接拒绝”的模式。但这还不能区分：

1. 5 档正确表达了 partial/substantial satisfaction；
2. 2 档只是过于严格；
3. 5 档只是把边界推向 positive。

需要人工查看原始 response/trajectory 和 rubric，尤其检查证据是否确实是“部分满足”，而不是明确完整满足。

## 3. `2 档对 → 5 档错`（B=5）

### B1. `healthbench_289a133b-7df3-4e36-b867-0ef5cf97fd39_a55ca0e4-6f2a-4e54-ad22-a903454c8104`

- benchmark：HealthBench；category：`context_seeking`；provisional semantic type：`graded_quality_or_safety`
- Gold：`0.3333333333333333` / binary=`False`
- 2 档 score：`0.0`（正确）；5 档 score：`0.5`（错误）
- point/check：`None`

### B2. `ruverbench_RB_58_0`

- benchmark：RuVer DeepResearch；category：`numbers`；provisional semantic type：`factual_numeric_verification`
- Gold：`0.0` / binary=`False`
- 2 档 score：`0.0`（正确）；5 档 score：`0.5`（错误）
- point/check：`RB_58::0`

### B3. `ruverbench_RB_9_1`

- benchmark：RuVer DeepResearch；category：`logic`；provisional semantic type：`logic_or_causal_verification`
- Gold：`0.0` / binary=`False`
- 2 档 score：`0.0`（正确）；5 档 score：`0.5`（错误）
- point/check：`RB_9::1`

### B4. `ruverbench_RB_30_0`

- benchmark：RuVer DeepResearch；category：`logic`；provisional semantic type：`logic_or_causal_verification`
- Gold：`0.0` / binary=`False`
- 2 档 score：`0.0`（正确）；5 档 score：`0.5`（错误）
- point/check：`RB_30::0`

### B5. `ruverbench_RR_93_1`

- benchmark：RuVer DeepResearch；category：`facts`；provisional semantic type：`factual_claim_verification`
- Gold：`0.0` / binary=`False`
- 2 档 score：`0.0`（正确）；5 档 score：`0.5`（错误）
- point/check：`RR_93::1`

B 组 5 条全部是 Gold negative，且 5 档均给出 `0.5`。这比“5 档更精细地表达了 partial positive”更像一个明确风险：对二元 coverage/absence criterion，5 档的中间分数可能把不满足推过 `>=0.5` 的 binary decision threshold，造成 false positive。

## 4. 按 benchmark 的 transition

| Benchmark | 2对5对 | 2对5错 (B) | 2错5对 (C) | 双错 |
|---|---:|---:|---:|---:|
| HealthBench | 11 | 1 | 3 | 5 |
| RuVer DeepResearch | 12 | 4 | 3 | 1 |
| RuVer AgenticCoding | 13 | 0 | 3 | 4 |

- HealthBench：C=3，B=1，净 +2；
- DeepResearch：C=3，B=4，净 -1；
- AgenticCoding：C=3，B=0，净 +3。

这与总体结果一致：5 档收益主要来自 HealthBench 和 AgenticCoding；DeepResearch 更适合保持二元 coverage 解释。

## 5. 初步 semantic granularity 审计

以下类型是基于 benchmark category/rubric 文本的**分析用 provisional label**，不是人工重新标注：

| provisional type | 含义 | 当前处理建议 |
|---|---|---|
| `binary_coverage_or_existence` | 是否出现某字段、行、格式或明确内容 | 优先比较 2 档；5 档中间分数需谨慎 |
| `binary_protocol_or_event_check` | 是否调用某工具/遵守某协议/发生某事件 | 2 档通常更自然；需结构化 evidence |
| `factual_numeric_verification` | 数字/数值条件是否满足 | 可二元，但若允许近似/部分覆盖需人工定义 |
| `factual_claim_verification` | 事实性陈述是否满足 | 需要区分 coverage 与 correctness |
| `logic_or_causal_verification` | 因果、逻辑关系是否满足 | 先固定 rubric 边界，再决定 resolution |
| `graded_quality_or_safety` | 整体质量、安全、完整性、部分满足 | 5 档更可能有表达优势 |
| `task_deliverable_or_process_quality` | 任务产物/过程质量 | 需要明确是否存在 partial 语义 |

本轮 9 个 C case 中，8 个 Gold positive 且多数 5 档输出中间分数；本轮 5 个 B case 全是 Gold negative 且 5 档输出 0.5。这同时支持两个方向：

- 对 graded quality，5 档可能修复 2 档的过度严格；
- 对 binary negative criterion，5 档的 0.5 可能造成 threshold false positive。

所以目前不能把“5 档收益”概括为单一能力提升。

## 6. 结论

当前最谨慎的结论是：

> 在 60 条新 Gold 上，5 档的净收益来自 9 个 `2 档错 → 5 档对` 与 5 个 `2 档对 → 5 档错` 的 paired transition。C 组主要是正例、B 组全部是负例；这更像是 anchor resolution 改变了 decision boundary，而不是已经证明 Judge 的 reasoning 变得更强。

> 5 档对 graded/quality/process 类型可能更合适；2 档对明确 binary coverage/existence/protocol 类型可能更合适。

McNemar descriptive p≈0.424，当前不能称为统计显著；后续需要扩大样本或重复 replay。

## 7. 下一步（按信息增益排序）

1. 人工复核 C=9 与 B=5 的原始 response/trajectory、rubric 和 Judge claims，明确是 `partial satisfaction` 还是 `strictness shift`；
2. 给 60 条 rubric/check 添加人工 semantic type：`binary_coverage`、`graded_quality`、`process`、`safety/completeness`；
3. 按 semantic type 分别计算 `Acc_2`、`Acc_5` 和 `ΔAcc`，避免 benchmark/domain 与 rubric semantics 混淆；
4. 对同一 60 条再做 3 repeats，测 resolution-specific stability；
5. 对 5 档分别测试 `τ=0.25/0.5/0.75`，区分 resolution gain 和 threshold shift。
