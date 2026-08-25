# Agent Judge architecture

本文档定义独立 Agent Judge 的目标架构。Judge 是一个独立的 agent 应用/服务，
不是 AgentEval 的一个大型 `LLMSkill`，也不是 `eval-system` 的运行模式。

## 1. 一句话定位

> 在 HarnessEval-W 的 Planner → Skill → Sub-agent → Parent validation 大框架不变的情况下，
> AgentEval 负责 Planner、rubric 和 skill 组织；独立 Judge 只替代其中的 subagent，
> 使它能够主动查询 runtime evidence、形成 claim/evidence chain，并返回可验证的结构化 judgment。

```text
┌──────────────────────────────────────────────────────────────────┐
│ eval-system                                                     │
│ 运行被测 agent，收集 attempt / trace / artifact                  │
└──────────────────────────────┬───────────────────────────────────┘
                               │ completed attempt reference
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│ AgentEval                                                       │
│ Case → Rubric → Skill plan → JudgeClient → aggregate/report     │
└──────────────────────────────┬───────────────────────────────────┘
                               │ JudgeRequest
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│ Agent Judge                                                     │
│ PydanticAI subagents + EvidenceProvider + EvidenceChain         │
└──────────────────────────────┬───────────────────────────────────┘
                               │ JudgeResponse
                               ▼
                         AgentEval report
```

## 2. 项目边界

### 2.1 eval-system

负责：

- 启动和运行被测 agent；
- 对接 Harbor、AgentOctagon 或其他 runtime；
- 收集 conversation、tool calls、events、trajectory、wire 和 workspace；
- 保存 completed attempt 和 artifact reference。

不负责：

- rubric 或 skill 选择；
- Judge 的 evidence query；
- Judge 的 LLM prompt、tool loop 或最终评分。

### 2.2 AgentEval

负责：

- 从 `eval-system` 读取 runtime artifact；
- 通过 `RuntimeAdapter` 生成 `EvalSample`；
- 根据 case 动态组织 skills；
- 从人类偏好案例生成 MetaRubric 和 case rubric；
- 把 case rubric 具体化为每个 skill/sub-question 的 JudgeRequest；
- 调 deterministic environment scorer；
- 通过 `JudgeClient` 调独立 Judge subagent；
- 聚合 deterministic/Judge 结果；
- 保存 plan、rubric、SkillResult、score 和报告。

不负责：

- agent loop；
- runtime trace 收集；
- EvidenceCatalog；
- evidence retrieval；
- claim verification；
- Judge agent 的执行过程。

AgentEval 中的 evidence tree 是 scoring provenance：

```text
case → selected skills → SkillResult → score/subscores/reasons
```

它不是 Judge 内部的 runtime evidence chain。

### 2.3 Agent Judge

负责：

- 接收 AgentEval 已经具体化的 rubric question；
- 通过 EvidenceProvider 查询 trace、wire、artifact 和 workspace；
- 形成该 question 的 claim/evidence chain；
- 区分 direct、derived、artifact 和 retrospective evidence；
- 处理该 question 的 missing evidence、contradiction 和 uncertainty；
- 返回一个结构化 subagent judgment、evidence references 和 provenance。

Judge 不负责选择 rubric question，也不负责最终 case-level 聚合。

Judge 自己运行自己的 agent loop，不由 `eval-system` 托管。

## 3. 为什么使用 PydanticAI

Judge 不从零实现 agent framework。PydanticAI 负责 Judge 内部的通用 agent 能力：

```text
Agent
  ├── model
  ├── system instructions
  ├── typed dependencies
  ├── function tools
  ├── structured output
  └── run/result/event handling
```

Judge 项目自己实现的是领域逻辑：

```text
EvidenceProvider
EvidenceCatalog
EvidenceChain
JudgePolicy
QuestionJudgment
ParentValidation
```

第一版不需要引入复杂的通用 workflow runtime。使用多个 PydanticAI Agent，
由 HarnessEval-W 风格的 Python 编排负责 Planner、question 分发和 parent aggregation。
只有出现复杂的并行、回环、复核和 checkpoint 需求时，才考虑 Pydantic Graph。

建议参考：

- PydanticAI Agents: <https://ai.pydantic.dev/agents/>
- PydanticAI tools: <https://ai.pydantic.dev/tools/>
- PydanticAI graphs: <https://ai.pydantic.dev/graph/>

## 4. 保持 HarnessEval-W 的大框架

Judge 不替换 HarnessEval-W 的基本组织方式，而是增强其中的 subagent：

```text
Case
  ↓
Planner
  ↓
Skill routing
  ↓
Rubric questions
  ↓
Question subagents
  ↓
Parent validator
  ↓
Final judgment
```

对应实现：

```text
AgentEval / HarnessEval-W layer
  ├── Case
  ├── Planner
  ├── Skill routing
  ├── Rubric / question instantiation
  ├── Parent validation
  └── aggregation contract

PydanticAI Judge layer
  ├── Question subagent
  ├── Evidence tools
  ├── Claim validation for this question
  └── structured subagent judgment
```

### 4.1 Planner（AgentEval）

Planner 完全属于 AgentEval/HarnessEval-W 层，负责：

```text
哪些 skill 适用
哪些 rubric question 需要判断
每个 question 的权重
每个 question 的 evidence requirements
如何聚合 question judgments
```

Planner 将一个具体 question 和对应 rubric 传给 Judge subagent；Judge 不重新规划 rubric。

### 4.2 Question subagent

每个 question subagent 只负责一个相对明确的问题。例如 launch-readiness case：

```text
work_package_boundaries
 dependency_structure
 parent_objective_coverage
 explicit_acceptance_criteria
 coordination_and_handoff_quality
```

每个 subagent 有自己的：

```text
rubric question
system instruction
evidence tools
output schema
```

### 4.3 Parent validator（AgentEval/HarnessEval-W）

Parent validator 属于 AgentEval/HarnessEval-W 的大框架。它接收 Judge subagent 返回的
question judgments，检查：

- claim 是否有 evidence reference；
- evidence 是否真的支持 claim；
- 是否把 retrospective artifact 当成 direct runtime evidence；
- 是否存在相互矛盾的 evidence；
- missing evidence 是否被错误地算作完成；
- question 分数是否符合 rubric anchor；
- 最终聚合是否可以审计。

Judge 可以返回 claim-level evidence，但不负责替代 parent validator。

## 5. Judge subagent execution

第一版每个 AgentEval skill/sub-question 调用一次独立 Judge subagent：

```text
AgentEval Planner
  → concrete rubric question
  → QuestionJudge.run()
  → QuestionJudgment
  → AgentEval parent validation / aggregation
```

如果未来 Judge 内部需要多轮证据复核，可以在单个 question subagent 内使用显式状态图；
这不是 AgentEval 的 Planner，也不是 case-level parent graph。目标 graph 是：

```text
START
  ↓
plan_questions
  ↓
question_judgments
  ↓
retrieve_evidence ───────────┐
  ↓                           │
verify_claims                 │ missing / contradiction
  ├── sufficient ─────────────┘
  ↓
parent_validation
  ↓
final_judgment
  ↓
validate_response
  ↓
END
```

推荐的 state：

```python
class JudgeState(TypedDict):
    request: JudgeRequest
    rubric_questions: list[dict]
    evidence_refs: list[str]
    evidence_records: list[dict]
    claims: list[dict]
    missing_evidence: list[dict]
    contradictions: list[dict]
    retrieval_round: int
    question_judgments: list[dict]
    final_response: dict | None
```

注意：Judge graph 是独立 Judge 的内部实现，不属于 AgentEval 的 `RunConfig` 或
`SkillRegistry`。

## 6. EvidenceProvider 与 evidence classes

Judge 通过 provider 读取 `trace_ref` 和 `artifact_ref`，而不是直接依赖
AgentOctagon 或 Harbor 的内部 Python 模块。

```python
class EvidenceProvider(Protocol):
    def search(self, query: EvidenceQuery) -> EvidenceSearchResult: ...
    def get(self, evidence_id: str) -> EvidenceRecord: ...
    def call_context(self, tool_call_id: str) -> EvidenceBundle: ...
    def related(self, evidence_id: str, relation: str) -> EvidenceSearchResult: ...
```

统一证据记录：

```python
class EvidenceRecord(BaseModel):
    evidence_id: str
    source: str
    line: int | None
    kind: str | None
    evidence_class: Literal[
        "direct_runtime_event",
        "derived_runtime_relation",
        "artifact_observation",
        "retrospective_artifact",
    ]
    claim_strength: Literal["direct", "derived", "indirect"]
    agent_id: str | None
    parent_agent_id: str | None
    tool_call_id: str | None
    timestamp: str | None
    content: dict[str, Any]
    related_evidence: list[str] = []
```

### 6.1 证据优先级

```text
direct_runtime_event
    > derived_runtime_relation
    > artifact_observation
    > retrospective_artifact
```

例如：

```text
agent:start / tool result
    = direct_runtime_event

根据 parent_agent_id + timestamp 推出的依赖顺序
    = derived_runtime_relation

最终文件中出现 security section
    = artifact_observation

coordination_log.json 声称“发生了 subagent_wait”
    = retrospective_artifact
```

`retrospective_artifact` 可以作为线索，但不能单独证明 runtime 事实。

### 6.2 streaming delta

EvidenceProvider 应过滤：

```text
llm:content:delta
llm:tool_call:created
arguments_delta
```

但保留：

```text
完整 tool arguments
完整 tool result
完成的 agent lifecycle
完成的 message/content
```

完整 raw capture 可以保存在 archive 中，用于 debug/replay，但不应作为 Judge 的主要
语义输入。

## 7. Evidence tools

第一版只需要四类 read-only tools：

```text
search_evidence
get_evidence
get_call_context
get_related_evidence
```

### `search_evidence`

```json
{
  "text": "security",
  "event_kinds": ["tool_call", "agent:start", "tool:result:done"],
  "agent_id": "optional",
  "limit": 12
}
```

### `get_call_context`

```json
{
  "tool_call_id": "call-123"
}
```

返回：

```text
tool arguments
→ agent:start
→ tool result
→ agent:end
→ related artifact changes
```

### `get_related_evidence`

```json
{
  "evidence_id": "trace.jsonl:35",
  "relation": "parent|child|same_call|downstream|artifact"
}
```

Judge 不应使用 `grep("wait")` 后直接把匹配结果当成 `subagent_wait`。工具返回必须带：

```text
matched field
evidence class
claim strength
source
line
evidence_id
```

## 8. Claim / evidence chain

Question subagent 不只返回 reason，而要返回 claims：

```python
class Claim(BaseModel):
    claim_id: str
    statement: str
    status: Literal[
        "supported",
        "partially_supported",
        "unverified",
        "contradictory",
    ]
    evidence_refs: list[str]
    missing_evidence: list[str] = []
```

例如：

```json
{
  "claim_id": "handoff-001",
  "statement": "integration agent received the security review output",
  "status": "partially_supported",
  "evidence_refs": ["trace.jsonl:35"],
  "missing_evidence": ["direct downstream-consumption event"]
}
```

最终分数必须可以追溯到：

```text
rubric question
  → claim
    → evidence refs
      → source record
```

## 9. Question judgment schema

```python
class QuestionJudgment(BaseModel):
    question_id: str
    score: float
    confidence: float
    claims: list[Claim]
    evidence_refs: list[str]
    missing_evidence: list[str]
    contradictions: list[str]
    status: Literal[
        "supported",
        "partially_supported",
        "unverified",
        "contradictory",
    ]
```

AgentEval/HarnessEval-W parent validator 输出：

```python
class FinalJudgment(BaseModel):
    score: float | None
    subscores: dict[str, float | None]
    reasons: dict[str, str]
    confidence: float | None
    question_judgments: list[QuestionJudgment]
    evidence_refs: list[str]
    findings: list[dict]
    status: Literal[
        "scored",
        "incomplete_evidence",
        "incompatible_input_contract",
        "judge_error",
    ]
```

## 10. 当前 launch-readiness case 的 question agents

### `work_package_boundaries`

查询：

```text
Agent dispatch arguments
scope
inputs
outputs
write scope
acceptance checks
```

### `dependency_structure`

查询：

```text
dispatch order
parent/child relation
agent lifecycle
dependency gate
integration start time
```

### `parent_objective_coverage`

查询：

```text
requirements
final artifacts
coverage mapping
source citations
missing sections
```

### `explicit_acceptance_criteria`

查询：

```text
acceptance events
QC checks
repair/revision
artifact validation
```

### `coordination_and_handoff_quality`

查询：

```text
assignment identity
handoff messages
result references
downstream consumption
provenance
```

## 11. AgentEval interface

AgentEval 只通过以下契约调用 Judge：

```python
from agenteval import HttpJudgeClient, JudgeClientSkill

client = HttpJudgeClient(
    "http://judge-service",
    endpoint="/v1/judge/evaluate",
    api_key=os.environ.get("JUDGE_API_KEY"),
)
skill = JudgeClientSkill(client, rubric)
```

请求：

```text
JudgeRequest (agenteval.judge_request.v1)
```

返回：

```text
JudgeResponse (agenteval.judge_response.v1)
```

AgentEval 不读取 Judge 的内部 evidence records，也不参与 Judge graph 的每一轮 tool call。

## 12. 实现阶段

### Phase 1：Judge MVP

- [ ] 新建独立 Judge package/service；
- [ ] 使用 PydanticAI Agent；
- [ ] 实现 `EvidenceProvider` local attempt adapter；
- [ ] 实现四个 read-only evidence tools；
- [ ] Judge 实现 `QuestionJudgment`；
- [ ] AgentEval/HarnessEval-W 负责 `FinalJudgment`；
- [ ] 对 launch-readiness case 完成一次 end-to-end judgment；
- [ ] 输出每次 tool call 和 evidence refs。

### Phase 2：稳定性

- [ ] evidence query budget；
- [ ] claim-level missing/contradiction validation；
- [ ] AgentEval parent validator 二次检查；
- [ ] judge self-consistency；
- [ ] prompt/rubric version provenance；
- [ ] PydanticAI message/event trace archive。

### Phase 3：集成

- [ ] 实现 `/v1/judge/evaluate`；
- [ ] AgentEval 使用 `HttpJudgeClient`；
- [ ] Harbor/AgentOctagon 只通过 `trace_ref`/`artifact_ref` 接入；
- [ ] 移除 AgentEval 内部的 `RuntimeEvidenceIndex` 和 judge tool loop；
- [ ] 保留 AgentEval 的 deterministic scorer、rubric planner、skill routing 和 aggregation。

## 13. 非目标

Judge 第一版不负责：

- 运行被测 agent；
- 采集被测 agent runtime；
- 修改 workspace；
- 修复被测 agent 的 artifact；
- 替代环境 deterministic scorer；
- 直接修改 AgentEval 的 rubric；
- 依赖 AgentOctagon/Harbor 内部模块；
- 将所有 raw delta 放入 prompt；
- 让 retrospective log 自动成为 runtime truth。

## HTTP integration and multi-question orchestration

The standalone Judge exposes one intentionally narrow endpoint:

```text
POST /v1/judge/evaluate
```

It accepts one `agenteval.judge_request.v1` request and executes exactly one
fully specified rubric question. The service constructs (or receives through
an adapter) a runtime-neutral `EvidenceCatalog`, invokes
`QuestionJudgeService`, and returns the question judgment together with:

- `provenance.query_trajectory`: every generic search/navigation call and the
  returned evidence ids;
- `provenance.evidence_manifest`: a compact catalog manifest;
- `provenance.integrity`: only schema-level checks (resolvable ids and
  supported claims having references).

The service does not plan a rubric, select questions, or aggregate scores.
`JUDGE_BASE_URL`, `JUDGE_API_KEY`, `JUDGE_MODEL`, and `JUDGE_PORT` configure
an OpenAI-compatible deployment without putting credentials in source files.

AgentEval's `MultiQuestionJudgeSkill` is the orchestration boundary. It sends
one HTTP/client request for each `Rubric.questions` item, retains each
question response, and computes a weighted mean using question weights. The
individual question responses and their provenance are stored in the skill's
`evidence.question_judgments` and `diagnostics.judge_provenance`; the report
index also exposes that provenance. No question-specific evidence retrieval,
mandatory tool call, investigation-depth score, or handoff proof rule is
implemented here.
