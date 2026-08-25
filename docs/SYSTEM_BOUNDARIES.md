# System boundaries: eval-system, AgentEval, and Judge

本文档冻结三个项目的身份边界。这里的 `Judge` 是独立的证据与判断系统，
不是 AgentEval 内部的一个大型 skill 实现。

## 1. 三层系统

```text
┌─────────────────────────────────────────────────────────────────────┐
│ eval-system                                                        │
│ 运行层：收集/管理 agent runtime，启动或接入 agent，保存 runtrace      │
│ Harbor / AgentOctagon / 其他 runtime                                │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ runtime artifact contract
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ AgentEval                                                          │
│ 评测编排壳：RuntimeAdapter、case、动态 skill/rubric、评分聚合、报告    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ JudgeRequest / trace reference
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Agent Judge                                                        │
│ 证据系统与判断层：EvidenceCatalog、检索、证据链、judge policy、LLM    │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.1 eval-system：运行与采集层

`eval-system` 负责：

- 启动、调度和等待 agent 运行；
- 对接 Harbor、AgentOctagon 或其他 runtime；
- 收集 conversation、tool calls、events、trajectory、wire records、
  workspace snapshot 和 runtime status；
- 保存可重放、可归档的 attempt/run 产物；
- 提供稳定的 artifact/attempt 访问接口。

`eval-system` **不负责**：

- 选择 rubric；
- 组织 AgentEval skills；
- 判断任务质量；
- 生成 LLM judge 分数；
- 解释人类偏好。

运行 agent、收集 runtime trace 和管理执行环境不是当前 AgentEval 的职责。

### 1.2 AgentEval：评测编排壳

AgentEval 的职责是把一个已存在的 case 和 runtime 产物组织成评测：

- 通过 `RuntimeAdapter` 读取 Harbor、AgentOctagon 或 JSON archive；
- 生成统一的 `EvalSample` 和 runtime-neutral trace reference；
- 根据 case 选择和动态组织 `Skill`；
- 维护 deterministic skill、environment scorer 和 LLM judge skill 的调用契约；
- 从人类偏好案例归纳 `MetaRubric`，并实例化 case-specific rubric；
- 调用外部或插件化 Judge；
- 聚合 deterministic/Judge 结果；
- 保存 AgentEval 自己的 plan、rubric、subscores、score、report 和 provenance。

AgentEval 的 evidence tree 指的是：

```text
case
  → selected skills
    → skill result
      → score / subscore / reason / provenance
```

它不是 runtime evidence chain，也不负责从原始 events 中检索证据。

AgentEval **不负责**：

- 执行 agent loop；
- 启动或调度 agent；
- 解析某个 runtime 的内部事件语义；
- 实现 `grep`、BM25、embedding 或其他 evidence retrieval；
- 决定某条 runtime event 是否足以证明某个 claim；
- 编写 judge prompt 的证据链策略；
- 代替独立 Judge 做最终语义判断。

### 1.3 Agent Judge：证据系统与判断层

Judge 是独立项目/服务。它接收 AgentEval 发来的 `JudgeRequest`，负责：

- 建立或访问 `EvidenceCatalog`；
- 对 trajectory、wire、tool arguments/results、artifact 和 workspace 做检索；
- 过滤 streaming delta，保留可审计的 semantic content；
- 建立事件之间的 call/lifecycle/parent-child/upstream-downstream 关系；
- 形成 question-level evidence bundle 和 evidence chain；
- 区分 direct runtime evidence、derived evidence 和 retrospective artifact；
- 处理缺失证据、冲突证据和不确定性；
- 调用 LLM、规则或多次投票完成 judgment；
- 返回 score、subscores、reasons、confidence 和 evidence references。

Judge 不应依赖 Harbor 或 AgentOctagon 的内部 Python 模块。它只消费
`eval-system` 提供的稳定 runtime/artifact contract。

Judge 的详细实现见 [`JUDGE_ARCHITECTURE.md`](JUDGE_ARCHITECTURE.md)。

## 2. 数据流边界

### 2.1 eval-system → AgentEval

最小输入是已完成或可读取的 attempt reference：

```json
{
  "sample_id": "attempt-123",
  "task_id": "launch_readiness_001",
  "attempt_ref": "octagon://attempt/attempt-123",
  "artifact_ref": "octagon://attempt/attempt-123/workspace",
  "runtime_status": "completed"
}
```

AgentEval 可以通过 adapter 将 reference 解析为 `EvalSample`，但不应在这里重新运行 agent。

### 2.2 AgentEval → Judge

AgentEval 向 Judge 发送评测上下文，而不是自己构造完整 evidence chain：

```python
@dataclass
class JudgeRequest:
    case: Case
    rubric: Rubric
    agent_output: str
    trace_ref: str | dict
    artifact_ref: str | dict
    deterministic_result: SkillResult | None
    metadata: dict
```

`trace_ref` 可以是：

- eval-system 的 attempt URI；
- 一个共享归档目录；
- 一个只读 evidence provider；
- 测试中的内存 fixture。

### 2.3 Judge → AgentEval

```python
@dataclass
class JudgeResponse:
    score: float | None
    subscores: dict[str, float]
    reasons: dict[str, str]
    confidence: float | None
    evidence_refs: list[str]
    findings: list[dict]
    provenance: dict
    status: str
```

`status` 必须区分：

```text
scored
incomplete_evidence
incompatible_input_contract
judge_error
```

不能把“没有可验证证据”静默转换成质量分 `0.0`。

## 3. Judge runtime ownership

Judge 的 agent loop 和 tool call 由独立 Judge 项目自己管理，不由 `eval-system` 托管。
Judge 不从零实现 agent framework，第一版使用 PydanticAI 组织 Judge agent、typed dependencies、read-only tools 和 structured output；
不把 Judge agent loop 放进 AgentEval。

```text
JudgeService
  ├── PydanticAI Agent
  ├── JudgePolicy / evidence policy
  ├── read-only evidence tools
  ├── EvidenceProvider
  ├── claim/evidence state
  └── structured JudgeResponse
```

推荐的最小 graph：

```text
START
  ↓
plan_questions
  ↓
retrieve_evidence ──┐
  ↓                  │ missing / contradiction
verify_claims ───────┘
  ↓
final_judgment
  ↓
validate_response
  ↓
END
```

PydanticAI 负责通用的 model→tools→model 循环、typed dependencies 和 structured output；
本项目的证据状态（rubric question、evidence refs、claims、missing evidence 和
contradictions）由 Judge 项目的领域模型和 policy 管理，而不是由 AgentEval 管理。

`eval-system` 不启动 Judge、不保存 Judge session，也不需要理解 Judge 的 tool call。
它只运行和收集被测 agent 的 runtime。AgentEval 通过 `JudgeClient` 调用独立 Judge。

## 3. Judge transport contract

AgentEval 提供一个不包含证据语义的 transport client：

```python
from agenteval import HttpJudgeClient, JudgeClientSkill

client = HttpJudgeClient(
    "http://judge-service",
    endpoint="/v1/judge/evaluate",
    api_key="$JUDGE_API_KEY",
)
skill = JudgeClientSkill(client, rubric)
```

请求体使用：

```text
POST /v1/judge/evaluate
Content-Type: application/json

JudgeRequest (agenteval.judge_request.v1)
```

返回体使用 `JudgeResponse` 的字段：

```json
{
  "score": 0.8,
  "subscores": {"decomposition": 0.9},
  "reasons": {"decomposition": "..."},
  "confidence": 0.8,
  "evidence_refs": ["trace.jsonl:35"],
  "findings": [],
  "provenance": {},
  "status": "scored"
}
```

这里的 HTTP path 是 AgentEval 侧的默认协议建议；独立 Judge 可以实现该协议，或通过
`JudgeClient` 的本地插件形式接入。AgentEval 不规定 Judge 内部如何实现 evidence
query、evidence chain 或 LLM session。

## 4. 三种系统之间不应发生的耦合

### AgentEval 不应知道 Judge 的内部工具

AgentEval 不应直接依赖：

```text
grep_runtime_evidence
EvidenceCatalog
EvidenceChain
BM25 index
embedding index
judge tool loop
```

这些属于 Judge 的内部实现。

### Judge 不应知道 AgentEval 的 skill registry

Judge 不应导入：

```text
SkillRegistry
RuleRouter
RunConfig
AgentEval report writer
```

它只接受结构化 rubric 和 JudgeRequest。

### eval-system 不应知道 rubric 语义

eval-system 只负责运行和保存事实，不应为了某个评分维度生成：

```text
package_acceptance
handoff_quality
launch_readiness_score
```

这些应由 AgentEval/Judge 根据 rubric 解释。

## 5. 当前代码的过渡状态

当前仓库中仍存在一些早期集成实现：

```text
src/agenteval/adapters/octagon_scorer.py
src/agenteval/adapters/runtime_evidence.py
src/agenteval/backends.py::infer_with_tools
```

它们用于验证 AgentOctagon 与 LLM judge 的适配，但不应被视为最终系统边界。
长期迁移方向是：

```text
OctagonLLMJudgeSkill
    → JudgeClientSkill

RuntimeEvidenceIndex
    → 独立 Judge 项目的 EvidenceCatalog

infer_with_tools / evidence tool loop
    → 独立 Judge session/runtime
```

在迁移完成前，AgentEval 可以保留兼容实现，但新功能不应继续把 evidence retrieval
和 judge policy 扩散到 AgentEval 核心。

## 6. 任务分解案例的职责分工

以 launch-readiness decomposition 为例：

### eval-system

记录事实：

```text
main agent 调用了哪些 subagent
调用参数是什么
什么时候开始/结束
产生了哪些 workspace 修改
哪些 tool call 返回成功/失败
```

### AgentEval

组织问题：

```text
work_package_boundaries
 dependency_structure
 parent_objective_coverage
 explicit_acceptance_criteria
 coordination_and_handoff_quality
```

并生成具体 case rubric，决定调用哪些 skill。

### Agent Judge

回答问题：

```text
哪些 package 有直接 runtime 证据？
依赖顺序是否由真实等待/生命周期记录支持？
handoff 是直接事件还是事后日志声称？
哪些结论只能算 inferred？
哪些维度因证据缺失而 unavailable？
```

这三个阶段不能混成一个 `OctagonLLMJudgeSkill`。

## 7. 设计原则

1. **先运行，后评测**：agent 执行属于 eval-system，不属于 AgentEval。
2. **先适配，后组织**：runtime-specific files 由 adapter 转成稳定 reference。
3. **先组织，后判断**：AgentEval 组织 case、rubric 和 skill；Judge 负责证据与判断。
4. **事实与偏好分离**：runtime 记录事实，人类偏好通过 rubric 影响判断标准。
5. **证据按需读取**：不要把 raw delta 或完整事件流直接塞进 judge prompt。
6. **证据来源分级**：runtime event、derived relation、artifact observation、retrospective report 必须区分。
7. **不可验证不等于零分**：输入契约不兼容或证据缺失应返回明确状态。
8. **跨 runtime 中立**：AgentEval 和 Judge 都不应绑定 AgentOctagon 的内部实现。
