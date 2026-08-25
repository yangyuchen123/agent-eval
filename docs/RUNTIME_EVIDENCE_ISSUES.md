# Runtime Evidence 评测问题、解决方案与状态

> 本文记录 AgentEval 在“最终产物评分已经稳定，但无法证明子 agent 协作真实发生”这一问题上的调查结论、设计决策和当前实现状态。
>
> 更新时间：2026-08-25

## 1. 背景：不是重做原有 Judge

当前系统实际包含两个互补的评测目标：

```text
A. Outcome / Artifact Judgment
   case + 人类 rubric + case-specific rubric + 最终产物

B. Runtime Coordination Judgment
   case question + runtrace + tool arguments/results + lifecycle + artifacts
```

A 已经能够得到相对稳定的结果。人类 rubric 案例先归纳为 MetaRubric，再由 AgentEval Planner
针对具体 case 生成 case-specific rubric，原有 Judge 根据 rubric 和最终产物评分。这个流程
对工作包设计、依赖结构、完整性、验收标准、证据边界和最终交付物质量是有效的。

B 解决的是另一类问题：最终产物不能单独证明父 agent 在运行时到底给子 agent 分配了什么任务、
子 agent 返回了什么、父 agent 是否回收了结果，以及下游 agent 是否真正消费了上游结果。

因此，Runtime Evidence Judge **不是替换原有 Artifact Judge**，也不是把所有评分迁移到独立 Judge。
它只增加 runtime coordination 的证据维度；rubric planner、question 组织、parent validation
和最终聚合仍然属于 AgentEval。

## 2. 问题清单与当前状态

| 编号 | 遇到的问题 | 解决方案 | 当前状态 |
|---|---|---|---|
| P1 | 原始 runtrace 含大量重复 delta，直接放进 prompt 体积过大且噪声严重 | 建立 runtime-neutral projection；过滤 streaming delta，保留完整语义 content、工具参数、工具结果、身份、时间和关联 ID | **部分解决**：catalog 已过滤 delta 并保留主要字段；仍需覆盖更多 runtime 变体 |
| P2 | 只看最终 artifact，无法证明子 agent 的真实任务分配 | 查询 Agent/function tool 的完整 arguments，保留 prompt、description、write scope、expected output 和 agent identity | **部分解决**：字段已保留并可查询；不同 runtime 的 parent/child 字段仍需适配 |
| P3 | 无法证明子 agent 返回了什么以及父 agent 是否回收 | 使用 tool_call_id、完整 tool result、agent lifecycle 和 call context 建立调用上下文 | **部分解决**：`get_call_context` 已有原型；上游返回值到下游输入的关联仍不完整 |
| P4 | 无法证明 handoff 是否被下游 agent 实际消费 | 查询上游结果、下游调用参数、消息内容、artifact 引用和父子 agent 关系，形成 claim → evidence 链 | **未完全解决**：能发现缺失证据，但尚未稳定恢复跨 agent 的数据流 |
| P5 | `coordination_log.json` 等事后产物容易被误当成运行时事实 | 给证据分级：`direct_runtime_event`、`derived_runtime_relation`、`artifact_observation`、`retrospective_artifact`；事后产物只能作为间接证据 | **已解决设计，部分实现**：catalog 已标记证据等级；parent policy 和自动校验尚未完成 |
| P6 | 不把完整 runtrace 放入 prompt 后，Judge 不知道具体 content | prompt 只提供索引说明；Judge 通过 `search/get/context/related` 工具按需查询完整记录 | **部分解决**：工具链已存在；搜索策略和重试机制仍需增强 |
| P7 | Judge 每次自行选择证据，查询结果可能不稳定 | 不在底层编码 question-specific 查询；增强通用搜索、结构化过滤、关系导航，并记录 Judge query trajectory | **部分解决**：通用工具已增强；Judge 是否继续调查仍由 agent 自主决定 |
| P8 | 原有 Judge 的整体高分把 artifact 质量和 runtime 协作质量混在一起 | 保留原有整体 Artifact Judgment；新增独立 question，例如 `assignment_quality`、`handoff_consumption` | **设计已确定，接入进行中** |
| P9 | deterministic scorer 的异常低分可能污染 LLM Judge | deterministic score 作为 evidence 而非指令；记录 scorer provenance；对异常/缺失 scorer 结果显式标记 | **部分解决**：旧 prompt 已有约束；还需要对 deterministic result 做有效性和异常检测 |
| P10 | AgentEval、eval-system、Judge 的职责边界混淆 | eval-system 只运行和采集；AgentEval 组织 rubric/skill、调用 Judge、聚合；独立 Judge 只替代 subagent 并查询证据 | **已解决设计和文档** |
| P11 | 直接比较旧整体分和新单问题分会得出错误结论 | 固定同一 case-specific rubric，将旧整体评分与新 question judgments 聚合后比较 | **已发现；公平基线实验尚未完成** |
| P12 | 需要真实模型验证，而不是只用 TestModel | 使用 OpenAI-compatible endpoint 进行重复运行，同时不将 API key 写入仓库或报告 | **已完成探索性验证**；正式多 case 稳定性实验尚未完成 |

## 3. 证据分类

### 3.1 直接运行时证据

这是证明 runtime fact 的最高强度证据，例如：

```text
agent:start / agent:end
functions.Agent 调用
完整 tool arguments
完整 tool result
subagent_message
subagent_wait
tool_call_id
agent_id / parent_agent_id
```

它们可以直接支持：

```text
某个 agent 被创建
某个任务被发送
某个工具调用返回了结果
某个生命周期已经结束
```

### 3.2 派生运行时关系

由多个直接事件关联得到的关系，例如：

```text
同一个 tool_call_id 的调用和结果
parent_agent_id → child agent
上游调用 → 下游调用的时间顺序
```

它不是原始事件，但可以通过稳定 ID 和规则复现，因此通常比 artifact 强。

### 3.3 Artifact observation

对 workspace 文件的直接观察，例如：

```text
文件存在
CSV 可以解析
JSON 字段完整
文件内容包含某个引用
```

它能证明交付物的状态，但不能自动证明交付物中的过程声明真实发生。

### 3.4 Retrospective artifact

`coordination_log.json`、dossier 中的流程总结、provenance 报告等属于这一类。

它们的意义是：

```text
作为检索线索
作为最终产物质量的评分对象
作为间接、可审计的过程声明
```

它们不能单独证明：

```text
某次 Agent 调用确实发生
某个返回值确实被下游接收
某个 handoff 确实在运行时完成
```

因此 Judge 可以引用 retrospective artifact，但必须标记其证据强度，不能把它升级为
`direct_runtime_event`。

## 4. Runtime projection 规则

### 4.1 必须过滤的内容

```text
llm:content:delta
arguments_delta
llm:tool_call:created
重复的 streaming fragment
```

这些记录属于采集层或传输层噪声，直接保留会造成：

- prompt 体积膨胀；
- 同一内容重复计数；
- Judge 被底层协议字段分散注意力；
- evidence ID 难以稳定复现。

### 4.2 必须保留的内容

```text
工具调用的完整 arguments
工具调用的完整 result
Agent prompt / description
消息 content
file_path / write_scope
agent_id / parent_agent_id
tool_call_id
timestamp
lifecycle state
error / ok
```

尤其不能只保留：

```text
kind + timestamp + tool_name
```

否则 Judge 只能知道“调用了某个工具”，却不知道：

```text
调用时传入了什么任务
要求子 agent 产出什么
子 agent 返回了什么
父 agent 后续如何处理返回值
```

## 5. Evidence Tool 设计

Evidence Tool 不是把完整 runtrace 重新塞回 prompt，而是提供一个只读查询面：

```text
Judge claim
  ↓
search_evidence
  ↓
get_evidence
  ↓
get_call_context
  ↓
get_related_evidence
  ↓
claim / evidence / missing evidence
```

当前原型工具：

```text
search_evidence
get_evidence
get_call_context
get_related_evidence
```

推荐的 question-level 证据查询顺序：

```text
1. 查找 Agent/function 调用和完整 arguments
2. 获取该调用的 tool_call 上下文
3. 查找对应 child agent 的 lifecycle
4. 获取 child agent 的完整返回结果
5. 查找下游 Agent 的调用参数或消息
6. 查询下游产物和引用
7. 检查上游结果是否能关联到下游输入
8. 形成 claim → evidence_refs → conclusion
```

对于 handoff 问题，以下链条缺任何一段都应该降低判断强度：

```text
dispatch
  → child execution
  → result return
  → parent collection
  → downstream input
  → downstream consumption
```

## 6. 目前已经验证的内容

截至 2026-08-25，使用案例：

```text
run/launch-readiness-decomposition-v1/attempt/
```

已验证：

```text
- EvidenceCatalog 可以加载 trace/events/wire
- streaming delta 可以被过滤
- 工具参数和完成结果可以保留
- evidence_id 可以稳定生成
- retrospective artifact 可以单独标记
- Judge 可以主动调用 evidence tools
- Judge 可以返回 claims、evidence_refs、missing_evidence 和 status
- 真实 gpt-5.6-luna endpoint 可以运行 QuestionJudge
```

独立 Judge 的真实重复运行得到：

```text
coordination score: 0.52, 0.25, 0.62
status: 三轮均为 partially_supported
```

它没有把 handoff/下游消费直接认定为已被证明，并明确列出了缺失的：

```text
parent-child agent 关联
实际 Agent 调用参数
上游返回值
下游接收参数
下游消费关系
```

这说明“证据链输出”已经可以工作。

## 7. 尚未解决的关键问题

### 7.1 证据检索的稳定性

真实运行中有一轮 Judge 返回了：

```text
evidence_refs = []
status = partially_supported
```

这不一定表示没有证据，更可能表示 Judge 生成的查询没有命中当前索引。因此需要：

- 更好的通用 lexical/semantic ranking；
- source/event/tool/agent/call/message 的结构化过滤；
- 通用关系导航和 query trajectory 分析；
- 查询结果为空时禁止高 confidence；
- 记录完整 query trajectory。

### 7.2 跨 agent 数据流关联

当前可以找到单个事件和调用上下文，但仍不能稳定证明：

```text
上游返回值 X
  ↓
被父 agent 收到
  ↓
被放入下游 agent 输入 Y
  ↓
被下游 agent 消费
```

需要 runtime adapter 提供更稳定的：

```text
message_id
parent_agent_id
child_agent_id
tool_call_id
upstream_result_ref
downstream_input_ref
```

### 7.3 Evidence claim policy

当前 Judge 会被要求引用证据，但还没有完全由程序强制验证：

```text
每个 supported claim 必须有 evidence_refs
retrospective artifact 不能单独支持 runtime claim
contradiction 必须降低 score 或 confidence
missing evidence 必须影响 score
```

这些应当在 Judge 输出后由 schema/policy 层再次检查。

### 7.4 公平的旧方案对照实验

之前历史上的旧 Judge 综合分多数在 `0.82~0.90`，它们评估的是：

```text
case + 人类 rubric + case-specific rubric + artifact/outcome
```

新 Judge 当前真实运行的 `0.25~0.62` 是单独的 runtime coordination question，不能直接和旧整体分比较。

公平比较应固定同一个 case-specific rubric，把新 Judge 的多个 question judgment 交给 AgentEval 聚合后，再与旧整体 Judge 比较。

## 8. 实施路线

```text
[已完成] 保留 content/arguments/result，过滤 delta
    ↓
[已完成] EvidenceCatalog 和只读证据工具原型
    ↓
[已完成] 单个 rubric question 的 PydanticAI Judge
    ↓
[已完成] generic search / structured filters / navigation
    ↓
[已完成] Judge query trajectory logging
    ↓
[进行中] claim/evidence/missing-evidence policy 校验
    ↓
[进行中] contradiction / missing evidence 自动补查
    ↓
[待实现] runtime adapter 的跨 agent correlation
    ↓
[待实现] QuestionJudge HTTP service
    ↓
[待实现] AgentEval 将 case rubric 拆成多个 question 并聚合
    ↓
[待实现] 多案例、固定 rubric、旧方案/新方案公平对照实验
```

## 9. 最终边界

```text
eval-system
  运行 agent，收集并保存 runtime

AgentEval
  归纳人类偏好，生成 case rubric，组织 questions，调用 Judge，聚合结果

独立 Agent Judge
  查询 runtime evidence，组织 claim/evidence chain，回答一个具体 question
```

最终系统同时输出两个正交结果：

```text
Artifact / Outcome Judgment
    +
Runtime Coordination Judgment
```

一个案例完全可能得到：

```text
artifact_quality = 0.88
runtime_coordination_evidence = 0.48
```

这不表示评分互相矛盾，而是表示：

> 最终产物质量较高，但当前 runtrace 还不足以证明子 agent 的任务分配、结果回收和下游消费在运行时真实完成。
