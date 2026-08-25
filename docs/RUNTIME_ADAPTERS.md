# Runtime adapters: eval-system artifacts into AgentEval

本文档说明 AgentEval 如何读取由 `eval-system` 收集的 AgentOctagon、Harbor 等 runtime 产物，并将其交给确定性 scorer、独立 Judge 或两者的组合。运行 agent、收集 runtime 和证据系统不属于本文档的 AgentEval 职责。

## 1. 设计边界

AgentEval 的核心不实现 agent loop，也不替代 `eval-system`、Harbor 或 AgentOctagon。它负责：

1. 接收 `eval-system` 产出的 runtime 产物；
2. 将不同 runtime 的产物转换为统一的 `EvalSample`；
3. 根据 case 和 rubric 选择评测 skills；
4. 调用环境 deterministic scorer 或独立 Judge；
5. 聚合分数并保存 AgentEval 自己的 history、manifest 和 leaderboard。

Evidence retrieval、evidence chain 和 Judge policy 属于独立 Judge 项目。

```
Harbor / AgentOctagon runtime
        │
        │  persisted attempt / JSON artifact
        ▼
RuntimeAdapter
        │
        ▼
EvalSample
        │
        ├── RuleSkill / environment scorer
        ├── LLMSkill / LLM-as-judge
        └── weighted aggregator
                │
                ▼
        AgentEval report
```

历史版本中的 `octagon-eval` 是兼容性编排入口，不代表目标架构。当前目标是由 `eval-system` 创建/运行 AgentOctagon 或 Harbor attempt，完成后由 AgentEval 读取 attempt 并评分。AgentEval 不启动 agent、不轮询 runtime，也不在本地重新实现 runtime。

## 2. 统一数据模型

runtime adapter 输出 `EvalSample`，包含：

| 字段 | 说明 |
| --- | --- |
| `sample_id` | 一次可评分样本的唯一 ID；AgentOctagon 中使用 `attempt_id` |
| `task_id` | 稳定任务 ID；用于不同 agent 的 paired comparison |
| `task` | case/task prompt |
| `output` | 最终文本输出 |
| `conversation` | 多轮对话和 tool calls |
| `artifacts` | workspace 中的文件/媒体引用 |
| `runtime_result` | runtime status、原始分数、错误和成本等 |
| `environment` | 环境名、运行目录等 |
| `context` | evaluator-only 数据，不发送给 agent |
| `agent` / `backend` | agent、model、provider 和 runtime provenance |

### AgentOctagon 读取范围

`AgentOctagonAdapter` 读取共享 `data-root` 中的：

```text
<data-root>/octagon.db
<data-root>/attempts/<attempt_id>/conversation.jsonl
<data-root>/attempts/<attempt_id>/trace.jsonl
<data-root>/attempts/<attempt_id>/events.jsonl
<data-root>/attempts/<attempt_id>/thinking.jsonl
<data-root>/attempts/<attempt_id>/trajectory.json
<data-root>/attempts/<attempt_id>/blade_history.json
<data-root>/attempts/<attempt_id>/final_state.json
<data-root>/attempts/<attempt_id>/skill_workspace/**
```

conversation 的 fallback 顺序是：

```text
conversation.jsonl → trajectory.json → blade_history.json
```

同一个 task 的不同 attempt 不会被合并：

```text
sample_id = attempt_id
 task_id  = stable task id
```

## 3. 三种评分模式

### 3.1 纯确定性评分

适用于环境有 `scorer.py` 的情况：

```text
OctagonEnvironmentSkill (RuleSkill)
    → envs/<env_name>/scorer.py
    → SkillResult.score ∈ [0, 1]
```

环境 scorer 的推荐接口：

```python
def score(
    *,
    attempt_id,
    task,
    env_db=None,
    trace=None,
    final_state=None,
    events=None,
):
    return [
        {
            "dimension": "correctness",
            "value": 80,       # 0..100；也支持 0..1
            "detail": "...",
        },
    ]
```

运行已有 attempt：

```bash
.venv/bin/agenteval octagon-score \
  --data-root /home/yang/agent-octagon/data \
  --env-root /home/yang/agent-octagon-envs \
  --env agent-workspace-smoke-test \
  --attempt-id <attempt_id> \
  --run-root run/octagon-deterministic
```

### 3.2 纯 LLM-as-judge

适用于环境没有确定性 scorer，或任务本身主要依赖 rubric 语义判断的情况。

```text
AgentEval JudgeClientSkill
    → JudgeRequest(case + rubric + trace/artifact references)
    → independent Agent Judge
    → JudgeResponse → SkillResult.score ∈ [0, 1]
```

此模式不要求 `scorer.py`：

```bash
.venv/bin/agenteval octagon-score \
  --data-root /home/yang/agent-octagon/data \
  --env-root /home/yang/agent-octagon-envs \
  --env <env_name> \
  --attempt-id <attempt_id> \
  --judge-only \
  --judge-base-url http://localhost:8000/v1 \
  --judge-model <judge_model> \
  --judge-api-key "$OPENAI_API_KEY" \
  --judge-rubric-file rubrics/<env_name>.txt \
  --run-root run/octagon-judge
```

Judge 返回的 JSON 至少应包含：

```json
{
  "score": 0.75,
  "subscores": {
    "correctness": 0.8,
    "completeness": 0.7
  },
  "reasons": {
    "correctness": "...",
    "completeness": "..."
  },
  "additive_findings": [],
  "confidence": 0.9
}
```

`score` 和 `subscores` 必须在 `[0, 1]`。LLMBackend 会保存 judge model、请求地址、usage、重试和响应元数据，便于审计和复现。

### 3.3 混合评分

混合模式保留两棵独立 evidence，不把确定性结果覆盖成 LLM 结果：

```text
OctagonEnvironmentSkill
    → deterministic environment score

OctagonLLMJudgeSkill
    → receives deterministic score as evidence
    → adds rubric/semantic score

weighted_case_score
    → final score
```

```bash
.venv/bin/agenteval octagon-score \
  --data-root /home/yang/agent-octagon/data \
  --env-root /home/yang/agent-octagon-envs \
  --env <env_name> \
  --attempt-id <attempt_id> \
  --judge-base-url http://localhost:8000/v1 \
  --judge-model <judge_model> \
  --judge-api-key "$OPENAI_API_KEY" \
  --judge-rubric-file rubrics/<env_name>.txt \
  --deterministic-weight 0.5 \
  --judge-weight 0.5 \
  --run-root run/octagon-hybrid
```

混合模式中，AgentEval 向独立 Judge 发送：

- task/case/metadata；
- case-specific rubric；
- agent 的最终输出；
- `trace_ref` / `artifact_ref`；
- 确定性 scorer 的原始维度、分数和理由。

Judge 如何查询 trace、组织 evidence chain 和决定语义分数不属于 AgentEval。确定性分数是
JudgeRequest 中的证据之一，不是必须照抄的答案；两种结果都由 AgentEval 分开保存。

默认权重：

```text
deterministic_weight = 0.5
judge_weight         = 0.5   # 只有提供 --judge-model 时才启用 judge skill
```

不提供 `--judge-model` 时，实际只运行确定性 skill，保持向后兼容。

## 4. 与 eval-system 的集成

运行 agent、创建/等待 AgentOctagon 或 Harbor run、收集 attempt 和保存 runtime trace
由前置的 `eval-system` 负责。AgentEval 从已经完成的 attempt 读取：

```text
eval-system
  → completed attempt / trace references
  → AgentOctagonAdapter 或 HarborAdapter
  → EvalSample
  → AgentEval skill/rubric plan
  → deterministic scorer / JudgeClient
  → AgentEval report
```

典型流程：

```bash
# 1. 由 eval-system 运行 agent 并保存 attempt
eval-system run \
  --runtime agent-octagon \
  --env <env_name> \
  --task-id <task_id> \
  --agent <agent> \
  --output /path/to/attempt

# 2. AgentEval 只读取已经完成的 attempt 并评分
.venv/bin/agenteval octagon-score \
  --data-root /path/to/eval-system/data \
  --env-root /path/to/agent-octgan-envs \
  --env <env_name> \
  --attempt-id <attempt_id> \
  --run-root run/octagon-score
```

仓库中历史版本的 `octagon-eval` 仍可能存在，用于兼容旧的 HTTP 编排流程；它不是
当前目标架构，也不应继续扩展为 AgentEval 的 runtime runner。

## 5. 结果文件

每个 AgentEval run 默认生成：

```text
run-root/
├── summary.json
├── leaderboard.csv
├── LEADERBOARD.md
├── evidence/<sample_id>.json
├── history.jsonl
└── run_manifest.json
```

`evidence/<sample_id>.json` 中的 `skill_results` 会明确区分：

```json
{
  "octagon_environment_scorer": {
    "status": "ok",
    "score": 0.8
  },
  "octagon_llm_judge": {
    "status": "ok",
    "score": 0.6
  }
}
```

纯 Judge 模式下：

```json
{
  "octagon_llm_judge": {
    "status": "ok",
    "score": 0.6,
    "evidence": {
      "deterministic_environment_score": null
    }
  }
}
```

## 6. Harbor 对接

Harbor 与 AgentOctagon 都是 runtime，AgentEval 不把它们的内部执行实现耦合进评分核心。

Harbor 适配有两种方式：

1. 将 Harbor 的 trial/result 导出为 JSON，使用 `JsonRuntimeAdapter`；
2. 为 Harbor 实现一个只读 `RuntimeAdapter`，将 Harbor 原生 trial、trajectory、artifacts 映射为 `EvalSample`。

`RuntimeAdapter` 的最小接口：

```python
class RuntimeAdapter(Protocol):
    name: str

    def iter_samples(self) -> Sequence[EvalSample]:
        ...
```

因此 Harbor 与 AgentOctagon 可以共享同一套：

```text
EvalSample → RuleSkill / LLMSkill → evidence/report
```

而不需要让 scorer 知道 runtime 的来源。

## 7. “任意环境”检查清单

在运行某个环境前检查：

- [ ] `env-root/<env_name>/tasks/<task_id>.json` 存在；
- [ ] runtime 使用的 `data-root` 与 AgentEval 参数一致；
- [ ] 确定性模式下存在可加载的 `scorer.py`；
- [ ] 纯 Judge 模式下提供 `--judge-model`、`--judge-base-url` 和 rubric；
- [ ] scorer 的依赖在当前 Python 环境可用；
- [ ] `eval-system` 已完成 agent run，并且 attempt/trace 已落盘；
- [ ] agent provider、API key、模型配置可用；
- [ ] 多轮环境的 conversation/events/final_state 已落盘；
- [ ] 需要外部服务的环境已启动其依赖。

“任意环境支持”的准确含义是：

> 任意符合 `eval-system` 导出契约、并且满足确定性 scorer 或 JudgeClient 配置的环境，都可以通过同一套 AgentEval pipeline 读取和评分。

它不意味着 AgentEval 会自动运行 agent、猜测环境的私有 scorer 签名、安装环境专属依赖或替代 runtime 的外部服务。

## 8. Human preference → case rubric

AgentEval 支持将人类偏好案例与具体 case rubric 分开存储：

```text
PreferenceExample
    ↓ rubric-induce
MetaRubric（跨 case 的人类偏好原则）
    ↓ rubric-instantiate
Rubric（当前 case 的具体评分问题）
    ↓
LLMSkill / judge
```

偏好案例不应直接当成 Judge prompt。它们应该记录：

```json
{
  "example_id": "pref-001",
  "case": {"task": "..."},
  "candidates": [
    {"id": "a", "output": "..."},
    {"id": "b", "output": "..."}
  ],
  "preference": {"preferred": "a", "rejected": "b"},
  "human_reason": ["does not invent unsupported facts"],
  "dimensions": ["evidence_boundedness"]
}
```

从偏好案例归纳 meta-rubric：

```bash
agenteval rubric-induce \
  --examples preferences/examples.jsonl \
  --output rubrics/human_preference.json \
  --rubric-id human_preference \
  --base-url http://localhost:8000/v1 \
  --model <planner-model>
```

再针对一个具体 case 实例化 rubric：

```bash
agenteval rubric-instantiate \
  --meta-rubric rubrics/human_preference.json \
  --case cases/launch_readiness.json \
  --output rubrics/launch_readiness.generated.json \
  --base-url http://localhost:8000/v1 \
  --model <planner-model>
```

生成的 case rubric 会保留：

- source meta-rubric；
- source preference examples；
- 每个问题对应的 source principles；
- case adaptation reason；
- planner model 和版本信息。

这样可以回答“这个具体评分标准来自哪些人类偏好案例”，并支持后续 rubric 版本迁移和人类复核。当前 Planner 只生成结构化 rubric，不自动修改人类偏好案例，也不直接负责最终评分。

### 8.1 在 Octagon 评测中自动生成 case rubric

如果已经有 `MetaRubric`，可以在每个 Octagon attempt 的 judge 调用前自动实例化
case-specific rubric：

```bash
agenteval octagon-score \
  --data-root /path/to/agent-octagon/run \
  --env-root /path/to/agent-octagon-envs \
  --env generated-launch-readiness-decomposition-v1 \
  --judge-base-url "$JUDGE_BASE_URL" \
  --judge-model "$JUDGE_MODEL" \
  --judge-api-key "$JUDGE_API_KEY" \
  --meta-rubric rubrics/human_preference.json \
  --generate-rubric \
  --deterministic-weight 0.5 \
  --judge-weight 0.5 \
  --run-root run/octagon-preference-hybrid
```

也可以直接提供偏好案例；系统会先调用 planner 归纳 `MetaRubric`，随后为每个
case 生成具体 rubric：

```bash
agenteval octagon-score \
  --data-root /path/to/agent-octagon/run \
  --env-root /path/to/agent-octagon-envs \
  --judge-base-url "$JUDGE_BASE_URL" \
  --judge-model "$JUDGE_MODEL" \
  --preference-examples preferences/examples.jsonl \
  --judge-only \
  --deterministic-weight 0 \
  --judge-weight 1
```

当启用该模式时：

1. 偏好案例仅用于归纳，不会直接作为 judge prompt；
2. 每个 case 的生成 rubric 只生成一次并缓存于本次进程；
3. judge 收到的是具体 rubric、case、output、conversation、artifacts、workspace、trace/events、final state，以及（若启用）确定性评分；
4. `evidence/<attempt>.json` 中保存 `meta_rubric`、case rubric 和 provenance，便于审计；
5. `--judge-rubric-file` 与生成模式同时使用时，生成的 case rubric 优先。

API key 只应通过环境变量传入，不要写入命令历史、仓库或评测产物。

### 8.2 Judge evidence-chain requirements

Octagon 的 judge 不应只收到最终 artifact 摘要，也不应把完整 `events.jsonl` 直接塞进
prompt。适配层会先建立 runtime-neutral 的 evidence index：

- 保留工具调用的参数、完成结果、tool-call ID、agent identity、时间和错误；
- 保留完成的 lifecycle/message 记录；
- 排除 `llm:content:delta`、`llm:tool_call:created` 等重复的流式增量；
- 给每条记录分配稳定的 `evidence_id`（例如 `trace.jsonl:42`）；
- prompt 只发送记录数量、来源、类型和查询说明，不发送全部证据正文。

judge 通过 OpenAI-compatible function tool `grep_runtime_evidence` 按需查证：

```json
{
  "pattern": "security|handoff|wait",
  "source": "trace.jsonl",
  "agent_id": "optional-agent-id",
  "limit": 12
}
```

工具返回带 `evidence_id` 的 bounded snippets，保留匹配记录中的 arguments、result、
content、身份和时间。judge 应先 grep 再对 assignment、dependency gate、handoff、
acceptance 或 repair 做事实性判断；找不到证据时只能标记为 `unverified`，不能把
retrospective `coordination_log.json` 当成运行时事实。这样既保留了可审计的语义 content，
也不会让重复 delta 主导 prompt 或 token 成本。

当前仍建议进一步把每个 case rubric question 转换成结构化 judge answer，并由
AgentEval 根据 question weights 计算最终分数。否则模型仍可以自由决定 subscore key
和整体 score，证据链虽然可查询，聚合仍可能波动。

### 8.3 Semantic runtrace 输入层

对于 AgentOctagon，judge 的逻辑运行轨迹输入是：

```text
trajectory.json + wire.jsonl
```

不要把 `events.jsonl` 中的 `llm:content:delta` 或
`llm:tool_call:created` 增量片段当作 runtrace。它们属于 raw capture 层，仅用于
底层 debug/replay 和环境 scorer 兼容。

AgentEval 的 `EvalSample.context` 现在分别保留：

```text
trajectory  # octagon-trajectory-v1 logical steps
wire        # octagon-wire-v1 normalized records
raw_trace   # legacy/raw trace compatibility
raw_events  # legacy/raw event compatibility
```

LLM judge prompt 使用 `runtrace.source = trajectory.json + wire.jsonl`，并同时保留
raw trace/event 的记录数作为审计元数据，但不把 raw delta 内容作为主要逻辑证据。

Semantic runtrace 会经过 runtime-neutral 的 prompt-size projection：只对记录数量、
嵌套深度和字符串长度做通用边界处理，不引入某一种评测任务的字段语义。完整归档
信息仍保留在原始 `trajectory.json` / `wire.jsonl` 文件中。目标是让普通 judge prompt
保持在约 100 KB 以内。


### 8.4 AgentEval Judge transport

AgentEval 提供一个纯 transport 层的 `HttpJudgeClient`：

```python
HttpJudgeClient(
    "http://judge-service",
    endpoint="/v1/judge/evaluate",
    api_key=os.environ.get("JUDGE_API_KEY"),
)
```

默认请求路径是：

```text
POST /v1/judge/evaluate
```

它只负责发送 `JudgeRequest`、解析 `JudgeResponse` 和记录 transport provenance；
它不实现证据查询或 judge tool loop。该路径是独立 Judge 的接入协议建议，不表示本仓库
内置了 Judge 服务。

## 9. Integration with eval-system and the independent Judge

目标数据流：

```text
eval-system
  → completed attempt / trace references
  → AgentOctagonAdapter or HarborAdapter
  → EvalSample
  → dynamic rubric + skill plan
  → JudgeClient (optional)
  → score aggregation and AgentEval report
```

AgentEval 不应直接 import Judge 的 EvidenceCatalog、evidence tools 或 judge session。
Judge 自己使用 PydanticAI 管理 model/tool loop；EvidenceProvider 和 evidence policy 由独立 Judge 管理；`eval-system` 不托管 Judge。
推荐的最小边界是：

```python
class JudgeClient(Protocol):
    def evaluate(self, request: JudgeRequest) -> JudgeResponse: ...
```

`JudgeRequest` 传递 case、rubric、最终输出和 trace/artifact reference；
`JudgeResponse` 返回 score、subscores、reasons、confidence、evidence references 和 provenance。

AgentEval 侧的正式薄接口是 `src/agenteval/judge.py` 中的 `JudgeRequest`、
`JudgeResponse`、`JudgeClient` 和 `JudgeClientSkill`。当前仓库中的
`OctagonLLMJudgeSkill`、`RuntimeEvidenceIndex` 和 tool-loop 属于过渡性原型，
用于验证接口，不是长期的 AgentEval 核心边界。
