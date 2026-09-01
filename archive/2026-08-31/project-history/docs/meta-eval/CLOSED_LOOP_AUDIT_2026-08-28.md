# 三系统闭环审计（2026-08-28）

## 结论摘要

现有系统不是“能力不存在”，而是主要缺少两条接线：

1. `eval-system` 已经能把 Harbor trial 归一为 `EvalSample`，并把
   `benchagent/evaluation.json` materialize 成 Harbor task；`agent-eval` 也已经
   能读取 Harbor trial 并评分，但没有把评分/证据/运行上下文投影为
   Benchmark Forge 可检索的既有事件。
2. Benchmark Forge 的 `OctagonKnowledgeBase` 已经是 benchmark 生成时使用的
   SQLite FTS 知识库，但只索引 environment/task/documentation/input，没有消费
   evaluation feedback；生成角色的 retrieval source filter 也没有包含反馈。

本次只补了这两处接线，没有新增 orchestrator、状态机、数据库或独立 diagnosis
schema。

## 当前真实调用链

### Benchmark 生成

`benchmark-forge`：

```text
benchmark_forge.cli
  → BenchmarkOrchestrator.run
  → PydanticAIRoleAgents.design/ground/allocate/verify
  → Benchmark / ExecutableTaskContract / EnvironmentIR
  → persistence / staging / materialization workflow
```

`OctagonKnowledgeBase` 通过 `pydantic_agents.py` 的 `context()` 注入 design、
grounding、allocation、executor、verification prompt。

legacy `benchagent` 另有：

```text
benchagent.cli
  → Pipeline.plan
  → DesignAgent / GroundingAgent / AllocationAgent
  → executor planning / verification
  → cache/<query_id>/evaluation.json
```

该 legacy pipeline 的 `KnowledgeBase` 主要存 verified sample few-shot examples，
目前没有 evaluation feedback 消费入口。

### 执行

`eval-system`：

```text
benchagent evaluation.json
  → integrations.benchagent.materialize_benchmark_tasks
  → Harbor task directory
  → HarborBackend.run / harbor run
  → Harbor trial
  → result.json + artifacts/ + agent/trajectory.json + verifier/
```

`HarborBackend` 通过 `TaskSpec / AgentSpec / EnvironmentSpec` 调 Harbor，
`HarborEvalLoader` 负责读取 trial；`hooks.collect_sample_on_end` 和
`collect_trial_on_end` 已提供运行结束回调。

Pi 的 ATIF/native session 转换已经存在于 `integrations.pi_atif`，测试覆盖了
Pi trajectory → ATIF。

### 评分

`agent-eval`：

```text
HarborEvalLoader / HarborAdapter
  → EvalSample
  → score_runtime_samples / AgentEval CLI
  → report.evidence
  → summary.json / leaderboard / evidence/
```

`EvalSample` 已同时携带 scenario、agent、artifacts、runtrace、scoring 和
原始 result；AgentEval 既有 report 也保留 Judge provenance/evidence refs。

### 反馈与学习

AgentOctagon 已存在：

- `octagon-diagnosis-v1`：terminal attempt 的 owner/confidence/evidence/action；
- `rubric_evolution`：gap → hypothesis → proposal → frozen corpus → Gold precheck
  → replay → human decision；
- `feedback` repository 和 learning state；
- `insights` evidence bundle。

但这些能力主要面向 AgentOctagon 自己的 experiment/rubric evolution；
`agent-eval` 的独立 report 不会自动进入 Benchmark Forge KB。Benchmark Forge
也没有从 AgentEval report 读取 iteration feedback 的路径。

## 能力盘点

| 目标能力 | 当前状态 | 代码依据 |
|---|---|---|
| benchmark 生成 | 已完整实现 | `benchmark_forge.orchestrator`, `service`, `pydantic_agents` |
| benchmark metadata / task contract | 已完整实现 | `domain.py`, `EnvironmentIR`, `TaskSpec` |
| benchmark → Harbor task | 部分实现但可接通 | `eval_system.integrations.benchagent`；当前主要接受 legacy `evaluation.json` |
| Harbor 运行 | 已完整实现 | `HarborBackend.run`, Harbor CLI |
| Pi runtrace / ATIF | 已完整实现 | `integrations.pi_atif`, Pi adapter tests |
| trial → unified sample | 已完整实现 | `HarborEvalLoader`, `HarborAdapter` |
| artifact + runtrace scoring | 已完整实现 | `score_runtime_samples`, AgentEval skills/Judge |
| evidence provenance | 已完整实现 | `CaseEvidence`, Judge provenance, `evidence/` |
| runtime terminal diagnosis | 已完整实现但边界不同 | AgentOctagon `automation/diagnostics.py` |
| benchmark/rubric/difficulty diagnosis | 已有输入和局部分析，未接通 | AgentEval reports + Forge metadata + Octagon rubric evolution |
| AgentEval → benchmark feedback | 确实缺失 | 原来没有 bridge |
| feedback → Forge KB | 确实缺失 | KB 只有 catalog index |
| Forge generation 消费 feedback | 已有 retrieval 机制但没有 feedback source | `OctagonKnowledgeBase.context`, role agents |
| Judge Gold calibration | 已部分实现 | Gold、MetaEvalRunner、已有 calibration experiments；已补交接 bundle |
| human preference / alignment | 部分实现 | preference-registry/arena、Forge alignment pipeline；尚未作为本闭环必经路径 |

## 真正的闭环断点

不是 Harbor、runtrace、artifact、AgentEval 或 Judge 本身缺失，而是：

```text
AgentEval summary/evidence
        X
Benchmark Forge existing KB
```

以及 Forge 的 retrieval source filter 没有反馈类别。

此外，当前实际 Harbor 运行还依赖 Docker daemon；本次小实验已验证到
`HarborBackend.run`，但运行环境返回 `Docker daemon is not running`，因此无法在
当前机器上新建 Harbor/Pi trial。这是执行基础设施阻塞，不是代码调用链断点。

## 最小修改

### 已修改

1. `eval-system/src/eval_system/integrations/feedback.py`

   把已有 `EvalSample` 和 AgentEval `summary.json` 投影为已有
   `BenchmarkEvent` 字段形状：`event_id/event_type/role/message/payload/timestamp`。
   payload 保留 benchmark/task/sample、agent、runtime、score、skill provenance、
   artifact/runtrace 路径和诊断建议。

2. `eval-system/src/eval_system/integrations/__main__.py`

   增加 `write-feedback` 命令，使用已有 Harbor loader 和 AgentEval report。

3. `benchmark-forge/.../octagon/knowledge.py`

   增加 `index_feedback_file()`，复用已有 `documents` + `documents_fts` 表，
   使用 `source_kind=iteration_feedback`。没有新表、新 KB、新 schema。

4. `benchmark-forge/.../pydantic_agents.py`

   将 `iteration_feedback` 加入已有各角色 retrieval source filter，让后续
   benchmark 生成可以看到历史反馈。

5. `benchmark-forge/scripts/ingest_evaluation_feedback.py`

   作为现有 Forge KB 的 CLI ingest 入口。

### 明确不修改

- Harbor 的运行逻辑；
- AgentOctagon 状态机；
- AgentEval scoring/Judge contract；
- 现有 Gold；
- AgentOctagon `octagon-diagnosis-v1`；
- `benchagent` 原有生成状态机；
- human preference/alignment protocol。

这些部分已有能力，当前闭环只需要连接，不应重构。

## 反馈归因边界

bridge 只做保守的 first-pass classification：

- runtime exception/non-completed → `infrastructure` 候选，`needs_review`；
- score 低于 0.4 → `unknown` + 低分复核；
- score 高于 0.9 → `unknown` + 高分复核；
- 其余 → `no_anomaly_detected`。

这不是替代人工归因，也不把“低分”直接写成“题目太难”。后续人工确认后，
反馈可以继续被 benchmark 生成器检索。

## 小规模验证

已运行 legacy benchagent smoke benchmark（10 个样本），取其中 1 个样本：

```text
benchmark generation: /tmp/benchagent_cache/smoke_test/evaluation.json
materialized task: run/closed-loop-smoke-20260828/harbor-tasks/
```

随后实际调用 `HarborBackend.run` 尝试启动 Harbor；当前主机 Docker Desktop
缺少 `/opt/docker-desktop/bin/com.docker.backend`，Harbor 返回：

```text
Docker daemon is not running. Please start Docker and try again.
```

因此 Harbor/Pi 新 trial 在本机被基础设施阻塞，没有把这个失败伪装成成功。
为了继续验证闭环接线，使用同一 benchagent 生成样本和同一 TaskSpec 通过已有
`LocalBackend` 做了 1 个真实本地 execution smoke：

```text
run/closed-loop-smoke-20260828/trials-real-local/
run/closed-loop-smoke-20260828/agent-eval-real/summary.json
run/closed-loop-smoke-20260828/agent-eval-real/evidence/
run/closed-loop-smoke-20260828/feedback-cli.jsonl
run/closed-loop-smoke-20260828/forge-kb-real.sqlite3
run/closed-loop-smoke-20260828/knowledge-retrieval-real.json
run/closed-loop-smoke-20260828/chain-result.json
```

实际链路为：

```text
benchagent evaluation.json
  → eval-system materialized task
  → eval-system LocalBackend smoke execution
  → TrialResult + artifact
  → AgentEval deterministic artifact/evidence scoring
  → existing BenchmarkEvent-shaped evaluation_feedback
  → existing Forge SQLite FTS KB
  → source_kind=iteration_feedback retrieval
```

该 smoke 的 score 为 `1.0`，由于高分超过 review threshold，反馈诊断为
`needs_review`，建议人工检查 rubric 松弛、漏洞和任务是否过简单。这验证了
高分异常路径也会留下可消费记录。Harbor/Pi 路径的真实验证需要恢复 Docker
daemon 后重复同一命令；代码接线不需要再改。

## 2026-08-28 Harbor + Pi 真实闭环补充验证

Docker daemon 恢复后，已用 1 个既有 benchagent sample 完成真实 Harbor + Pi
单 case 运行，不再使用 LocalBackend fallback：

```text
benchagent evaluation.json
  → eval-system materialize Harbor task
  → Harbor 0.22.0 / Docker 28.4.0
  → Pi 0.84.3 / gpt-5.6-luna
  → Pi native JSONL + ATIF trajectory.json + answer.txt
  → AgentEval independent Judge + frozen case Gold rubric
  → score/subscores/evidence
  → evaluation_feedback
  → Forge existing SQLite FTS KB
  → design-role iteration_feedback retrieval
```

可检查的证明入口：

```text
run/closed-loop-smoke-20260828/chain-result-harbor-pi.json
run/closed-loop-smoke-20260828/trials-harbor-pi-custom/
run/closed-loop-smoke-20260828/agent-eval-harbor-pi-judge/
run/closed-loop-smoke-20260828/feedback-harbor-pi.jsonl
run/closed-loop-smoke-20260828/forge-kb-harbor-pi.sqlite3
run/closed-loop-smoke-20260828/knowledge-retrieval-harbor-pi.json
```

该 case 的 Harbor verifier reward 为 `0.0`，AgentEval 总分为 `0.75`，分项为：

```text
semantic_answer_correctness = 1.0
artifact_contract_compliance = 0.0
runtime_evidence_quality = 1.0
```

证据显示 Pi 将 `0` 写入 `answer.txt`，语义上正确选择 option 0，但 verifier
只接受完整答案文本 `The bridge will close Monday.`。反馈桥因此依据
verifier/Judge 的显著分歧形成保守诊断：

```text
status = needs_review
suspected_owner = benchmark_or_scoring
reason = verifier reward (0) and AgentEval score (0.75) materially disagree
```

它没有把该结果误标成 agent 失败或 benchmark 太难。该反馈已以已有
`evaluation_feedback`/`BenchmarkEvent` 形状写入 Forge 原有 KB，并能由 design
role 以 `source_kind=iteration_feedback` 检索。

本次真实运行还补齐了三个窄断点：

1. Harbor task TOML name 投影为合法 `org/name`，稳定 benchmark task_id 留在 Spec；
2. loader 在缺少 post-run ATIF 时，从已有 Pi native session 做 read-side ATIF
   projection；
3. Judge 的 artifact-only question 可从 `artifact_ref.trial_dir` 建 evidence
   catalog，不再错误产生 `incomplete_evidence`。
