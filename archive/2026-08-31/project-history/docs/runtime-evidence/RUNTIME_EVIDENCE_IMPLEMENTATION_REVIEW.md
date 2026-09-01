# Runtime Evidence 当前实现审查与验证

更新时间：2026-08-25

本文严格遵循 Agent-only Judge 边界：Evidence Layer 只提供可搜索、可导航的 runtime environment，
不根据 rubric question 预先提取证据，也不实现 `verify_handoff`、`verify_assignment` 或其他
带评价语义的 deterministic retrieval。

## 1. 已符合设计的部分

### 1.1 Judge 仍然自主调查

独立 Judge 接收一个具体 question，工具只提供通用能力：

```text
search_evidence
get_evidence
get_call_context
get_related_evidence
```

Judge 自己决定：

- 先搜什么；
- 是否获取完整记录；
- 是否跟踪同一个 tool call；
- 是否沿 parent/child、same_agent、before/after 或 message 关系继续调查；
- 是否继续寻找反证。

代码中没有加入 question-specific 的 `find_handoff_evidence`、`verify_consumption` 或
mandatory handoff query。

### 1.2 projection 已经去除底层噪声

`EvidenceCatalog.from_attempt_dir()` 会过滤：

```text
llm:content:delta
arguments_delta
llm:tool_call:created
```

同时保留：

```text
arguments
result
content
description
prompt
file_path
write_scope
expected_output
tool_call_id
message_id
agent_id
parent_agent_id
timestamp
lifecycle state
```

对 AgentOctagon wire 记录还会读取通用的：

```text
correlation.agent_id
correlation.parent_agent_id
correlation.logical_call_id
correlation.turn_id
data
 time.timestamp
```

完整 `data` 被保留在 record content 中，但不会预先全部放入 Judge prompt。

### 1.3 搜索支持自然语言和结构化过滤

当前 `EvidenceQuery` 支持：

```text
text
source
event_type
kind
tool_name
agent_id
parent_agent_id
target_agent_id
tool_call_id
message_id
before
after
limit
```

自然语言查询使用通用 lexical matching 和结果 ranking；结构化字段用于精确过滤。
这解决了 Judge 必须知道原始 runtime JSON schema 的问题，但不替 Judge 解释查询含义。

### 1.4 导航 primitive 已扩展

除 `same_call` 外，catalog 现在支持通用关系：

```text
same_agent
parent
child
before
after
related_message
artifact
related
downstream
```

这些关系只回答“哪些记录相关”，不会回答“这是否构成合格 handoff”。

### 1.5 Judge query trajectory 已记录

`EvidenceCatalog` 和 `InMemoryEvidenceProvider` 记录：

```text
operation
query / navigation arguments
result_ids
```

`QuestionJudgeService.last_query_trajectory` 暴露本次 Judge 调查轨迹，用来区分：

```text
search environment failure
vs
Judge investigation failure
```

## 2. 仍然存在的下沉 reasoning 风险

以下风险仍然需要保持警惕：

### R1：按 question 名称在 catalog 内特殊处理

当前没有发现这种实现，不能加入：

```python
if question_id == "handoff": ...
```

任何基于 rubric 语义的自动检索都会把 Evidence Layer 变成 deterministic grader。

### R2：把 relation 结果自动解释成 judgment

`related(..., "child")` 只返回相关记录，不能自动返回：

```text
child completed
handoff verified
consumption proved
```

### R3：用 artifact 结果覆盖 runtime 缺口

文件存在、内容完整、coordination log 写了 `accepted`，只能作为 artifact observation 或
retrospective artifact。不能在 catalog 层自动升级为 direct runtime evidence。

### R4：自然语言搜索的 ranking 变成隐式答案

当前 lexical ranking 只决定候选记录顺序，不应该添加：

```text
handoff score
assignment confidence
consumption verdict
```

如果后续需要更强的 ranking，只能优化搜索相关性，并保留候选证据的完整 provenance。

## 3. 本轮优先修改的 5 个点

### M1：补全 runtime-neutral 字段

已实现。新增/规范化：

```text
event_type
actor_agent_id
target_agent_id
agent_id
parent_agent_id
tool_name
tool_call_id
message_id
file_path
lifecycle_state
```

并兼容旧的 `kind` / `agent_id` 字段。

### M2：修复 wire projection 丢失 correlation 的问题

已实现。旧实现没有读取 AgentOctagon wire 的：

```text
correlation.agent_id
correlation.parent_agent_id
correlation.logical_call_id
correlation.turn_id
```

现在这些字段会进入统一 EvidenceRecord。

### M3：增强通用 semantic search 和 structured filter

已实现：

- 自然语言 query 不再要求完整字符串原样出现在 record 中；
- 英文词、identifier、CJK 字符被拆分为通用查询项；
- 结果按 query term 命中数排序；
- 支持 event/tool/agent/call/message/time 等结构化过滤。

这不是 handoff retrieval，因为搜索层不知道当前 question 的评价含义。

### M4：扩展通用 navigation

已实现：

```text
same_agent
parent
child
before
after
related_message
```

这些能力只用于沿 runtime 关系继续调查。

### M5：记录 Judge query trajectory

已实现：

```python
service.last_query_trajectory
```

它记录 Judge 实际调用的搜索和导航操作，便于后续判断是：

- catalog 没有返回实际存在的记录；还是
- Judge 根本没有继续搜索、获取上下文或跟踪关系。

## 4. 使用真实 trace 的验证

验证输入：

```text
run/launch-readiness-decomposition-v1/attempt/
```

当前 catalog manifest：

```json
{
  "record_count": 340,
  "sources": {
    "trace.jsonl": 56,
    "events.jsonl": 245,
    "wire.jsonl": 39
  },
  "semantic_field_counts": {
    "arguments": 56,
    "result": 56,
    "content": 180,
    "tool_call_id": 155,
    "agent_id": 39
  }
}
```

通用搜索验证：

```text
search(tool_name="Agent")                  → 7 条
search(event_type=["agent:start", "agent:end"]) → 14 条
search(agent_id="agent:35e46969")           → 2 条 wire 记录
search(text="父 agent 给 research agent 分配了什么任务") → 命中候选记录
```

这证明 projection、结构化过滤和自然语言搜索都能访问真实 runtime content。

## 5.1 后续 evidence sufficiency audit

针对两轮 `score=0.88` 的离线证据充分性审计见：

- `run/launch-readiness-preference-study/evidence_sufficiency_audit_2026-08-25.md`
- `run/launch-readiness-preference-study/evidence_sufficiency_audit_2026-08-25.json`

审计发现两轮 investigation depth 都为 1：只有 search，没有 `get_evidence`、`get_call_context` 或 `get_related_evidence`。这不是修改 Judge 行为的结论，而是用于区分相关证据、调查不足和证据充分性不足的诊断结果。

## 5. 真实 Judge 验证与失败分类

使用真实 `gpt-5.6-luna`，同一真实 trace 运行两轮，结果为：

```text
round 1: score = 0.88, status = supported
round 2: score = 0.88, status = supported
```

两轮都产生了非空 evidence refs，并引用了真实 trace 记录。

### 5.1 观察到的 Judge 调查行为

Judge 实际使用了多次自然语言搜索，例如：

```text
launch readiness seven subagents staged reviews integration QC handoffs
remediation_plan.csv handoff downstream consumer handoff acceptance
seven subagents staged reviews integration QC handoffs artifacts
```

其中有一次 query 返回空结果：

```text
coordination_and_handoff_quality → []
```

但 Judge 后续继续使用更宽的 runtime/content 查询，最终获得了证据。因此这次不是最终的
search environment failure。

### 5.2 当前判断

```text
Search environment failure: 本轮未观察到最终失败
Judge investigation failure: 本轮未观察到停止后无证据的情况
```

不过也观察到一个重要风险：Judge 主要使用了自然语言 broad search，没有稳定调用
`get_evidence` / `get_call_context` / `get_related_evidence` 去追踪全部关联关系。因此：

```text
工具可搜索性：已经改善
Judge 是否充分调查：仍然取决于模型行为
证据链是否一定闭合：尚未保证
```

本轮 0.88 不能解释为 runtime handoff 已被完全证明。它只能说明当前 Judge 在本案例上找到了
较多候选 runtime content，并据此形成了高判断；是否应该给到这么高的分数，仍属于 Judge
investigation policy 和后续 claim validation 的问题，而不是由 EvidenceCatalog 自动决定。

## 6. 当前未解决事项

### 已解决

```text
- delta 过滤
- 完整 arguments/result/content 保留
- wire correlation projection
- runtime-neutral 字段
- generic semantic search
- structured filters
- generic navigation primitives
- query trajectory logging
```

### 部分解决

```text
- 不同 runtime 的字段映射完整性
- 自然语言搜索的相关性
- parent/child 与 tool/message 的跨文件关联
- Judge 是否会主动 follow context
```

### 尚未解决

```text
- 多 runtime 的统一 correlation contract
- 更可靠的 semantic ranking（仍不能引入 rubric 语义）
- query trajectory 的持久化 HTTP/report schema
- claim/evidence 的通用输出后校验
- runtime Evidence Graph / DAG
- 多 case 真实稳定性实验
```

## 7. 后续顺序

```text
1. 继续完善 runtime-neutral projection 的跨 runtime 映射
2. 观察真实 Judge query trajectory
3. 根据实际漏检样本改进 search/index/navigation
4. 区分 catalog failure 和 Judge investigation failure
5. 稳定后再考虑 Evidence Graph / DAG
```

暂不实现：

```text
mandatory evidence query
question-specific retrieval plan
verify_handoff / verify_assignment
automatic handoff proof
deterministic runtime scorer
```
