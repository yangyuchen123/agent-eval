# A/B/C/D Slice Feature Variable Specification

版本：`feature-vars.v1`
日期：2026-09-01
状态：冻结

## 目的

把 109 条 criterion 的关键属性从“分析时临时判断”变成固定、机器可读、可复用的实验变量。

这些变量当前用于：

- A/B/C/D 的分层准确率；
- paired transition 分析；
- 后续 repeat 的固定 strata；
- 检查条件间 Gold/输入分布是否一致。

注意：当前数据集中的这些属性是**观察变量/分层变量**，不是本次 A/B/C/D 主动操纵的 treatment。A/B/C/D 的 treatment 仍然是 Judge protocol。若要声称因果效果，必须在 manifest 中声明重新采样或构造平衡 factorial set。

## 冻结变量

### 1. `rubric_type_primary`

互斥主类别，按以下优先级取第一个命中的类别：

```text
compound > tool-use > style > frequency > process > outcome
```

规则：

- `compound`：文本包含多个逻辑/流程约束（至少两个 `and/or/then/if/unless/before/after/while`，或 Step 1/Step 2、both、all of the following、分号、长复合 and 结构）；
- `tool-use`：包含 tool、tool call、browser_action、TodoWrite、WebSearch、attempt_completion、Bash、Task/subagent 等；
- `style`：包含 concise、emoji、Markdown、naming、language、professional、CLI、format 等；
- `frequency`：包含 frequent/frequently/consistently/every/each/always/repeatedly/throughout/at any given time 等；
- `process`：包含 before/after/sequence/workflow/process/wait/first/finally 等；
- `outcome`：其他 criterion。

`compound` 优先，保证主类别互斥；因此主类别分布可能不均衡。

### 2. `rubric_type_tags`

非互斥标签，用于回答一个 criterion 同时具有什么语义属性。标签集合固定为：

```text
tool-use, style, frequency, process, outcome, compound
```

一个 criterion 可以拥有多个 tag，tag 计数不要求加总为 109。

### 3. `gold_polarity`

直接来自冻结 Gold：

```text
gold_true | gold_false
```

不允许根据 Judge prediction 重写。

### 4. `trajectory_length`

使用冻结 AgenticCoding trajectory 的 message/event 数：

```text
short_<=20_events       event_count <= 20
medium_21_60_events     21 <= event_count <= 60
long_>60_events         event_count > 60
```

`event_count` 和 `char_count` 同时保存；主分层只使用 event_count。

### 5. `evidence_locality`

当前版本明确命名为：

```text
evidence_locality_proxy_C_v1
```

它来自冻结 C 条件的 EvidenceCollector packet，仅作为预先冻结的诊断 proxy：

```text
clear：存在 criterion-linked evidence item，含 excerpt 和 polarity，且该 criterion 没有 missing evidence；
not_clear：否则。
```

它不是人工 Gold，也不是独立 oracle。由于它来自 C 的 collector，不能用于声称 evidence locality 对 C 的因果影响；正式报告必须保留 `proxy_C` 后缀，避免误读。

### 6. `global_context_requirement`

基于 criterion 文本的固定词法规则：若出现以下任一 marker，标记为 `required_or_global`：

```text
throughout, consistently, overall, entire, complete, all, each, every,
at any given time, sequence, before, after, rather than, only, multiple,
across, in a single, when using
```

否则标记为：

```text
local_or_single_event
```

该变量表示 rubric 文本是否显式要求跨事件/整体判断，不表示真实任务一定需要多少上下文。

### 7. `ambiguity`

目标模糊词集合冻结为：

```text
frequent, frequently, concise, properly, broad, appropriate,
appropriately, relevant, suitable, reasonable, clearly, consistent,
consistently, enough, significant, unnecessary, regularly
```

命中任一词：

```text
ambiguous_present
```

否则：

```text
no_target_ambiguous_word
```

同时保存 `ambiguous_words`，便于后续分析具体词的影响。

## 数据集中的当前分布

本版本生成的 `feature_labels.jsonl` 固定记录 109 条 criterion。当前观察到：

- primary compound：61；outcome：15；tool-use：25；process：2；style：6；
- overlapping tags：compound 61、tool-use 47、outcome 44、process 22、style 19、frequency 6；
- Gold true：76；Gold false：33；
- short：38；medium：51；long：20；
- evidence proxy clear：32；not_clear：77；
- global：59；local：50；
- ambiguity present：25；absent：84。

## 变量使用规则

正式 A/B/C/D 报告必须：

1. 使用同一份 `feature_labels.jsonl`；
2. 不在每个 condition 内重新分类；
3. 报告每个 slice 的 n 和 Gold true/false 分布；
4. 对 overlapping tags 单独说明分母不同；
5. 对 n 很小的 slice 只做描述，不做强结论；
6. 将 `evidence_locality_proxy_C_v1` 与真正独立 evidence Gold 分开。

## 后续 factorial 实验的 treatment 设计

如果后续要研究 feature 与 protocol 的交互，推荐使用：

```text
protocol ∈ {A,B,C,D}
× rubric_type_primary
× gold_polarity
× trajectory_length
× global_context_requirement
× ambiguity
```

`evidence_locality_proxy_C_v1` 只做诊断分层，不作为当前 C 的独立 treatment factor。

由于当前 109 条无法填满所有组合，不允许把稀疏组合的结果解释成完整 factorial effect；应先声明目标组合并按固定 feature labels 进行分层抽样或增加 Gold。
