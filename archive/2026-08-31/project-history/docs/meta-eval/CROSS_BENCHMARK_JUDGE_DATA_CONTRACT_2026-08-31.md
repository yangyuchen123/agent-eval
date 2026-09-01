 

# Cross-Benchmark Judge 数据契约与 AgentEval 交互说明

日期：2026-08-31
状态：审计文档 / pilot 结果解释，不改变 AgentEval、Judge 或 benchmark 评分逻辑。

## 1. 文档目的

当前已经使用三个外部 benchmark 对 AgentEval Judge 做了小规模 pilot：

| Benchmark                | Pilot 数据位置                                                  | 样本单位                                |
| ------------------------ | --------------------------------------------------------------- | --------------------------------------- |
| HealthBench              | `run/meta_eval/healthbench-gold-v1/`                          | prompt + completion + 一个 rubric       |
| RuVerBench DeepResearch  | `run/meta_eval/ruverbench-agent-eval-pilot-v1/`               | research response + 一个 rubric point   |
| RuVerBench AgenticCoding | `run/meta_eval/ruverbench-agenticcoding-agent-eval-pilot-v1/` | coding trajectory + 一个 checklist item |

本文件回答以下问题：

1. 三个 benchmark 的原始数据结构分别是什么；
2. 它们如何被转换为 AgentEval Judge 输入；
3. 哪些字段真正进入了 Judge；
4. Gold label 如何与 Judge 输出对齐；
5. 当前 pilot 到底测到了什么；
6. 当前 pilot 还没有测到什么；
7. 如何从当前单问题 Judge pilot 演进到完整 AgentEval meta-eval。

---

## 2. 关键结论

当前三个 pilot 实际测试的是：

```text
QuestionJudgeService

给定：
  一个 task/question
  一个 response 或 trajectory
  一个 rubric question

输出：
  一个 QuestionJudgment
```

而不是完整的：

```text
AgentEval Runner
→ Router
→ SkillRegistry
→ EvidenceProvider
→ MultiQuestionJudgeSkill
→ SkillResult
→ CaseEvidence
→ history/cache/report
```

因此当前结果可以说明：

> 在固定的 question、response/trajectory 和单个 rubric criterion 下，Judge 是否能与外部 Gold label 一致。

当前结果不能完全说明：

- AgentEval Router 是否选择了正确的 skill；
- 多个 rubric question 是否正确聚合；
- Judge 是否通过 EvidenceProvider 正确检索 runtrace；
- artifact evidence 与 runtime evidence 的混合判断是否正确；
- AgentEval 完整 Runner 的缓存、历史和 provenance 是否正确工作。

---

## 3. AgentEval 的核心数据模型

### 3.1 `Case`

定义位置：

```text
src/agenteval/protocols.py
```

核心结构：

```python
@dataclass(frozen=True)
class Case:
    case_id: str
    task: str
    expected: dict[str, Any]
    context: dict[str, Any]
    metadata: dict[str, Any]
```

语义：

| 字段         | 语义                                                                                  |
| ------------ | ------------------------------------------------------------------------------------- |
| `case_id`  | 一个评测实例的稳定 ID                                                                 |
| `task`     | 被评估任务，通常是用户问题、任务描述或 benchmark instruction                          |
| `expected` | 可选的 Gold、成功条件或 deterministic reference                                       |
| `context`  | evaluator-only 输入，不暴露给被评估 Agent，可包含 trace、artifact、state、verifier 等 |
| `metadata` | benchmark、版本、来源、运行和 provenance 信息                                         |

`Case.context` 的设计非常重要。它用于表达：

```text
被评估 Agent 看到的任务输入
```

与：

```text
Evaluator 为了判断而加载的内部证据
```

之间的边界。

### 3.2 `JudgeRequest`

定义位置：

```text
src/agenteval/judge.py
judge/src/agentjudge/models.py
```

核心结构：

```json
{
  "schema_version": "agenteval.judge_request.v1",
  "case": {},
  "rubric": {},
  "rubric_question": {},
  "agent_output": "",
  "trace_ref": null,
  "artifact_ref": null,
  "deterministic_result": null,
  "metadata": {}
}
```

字段说明：

| 字段                     | 来源/用途                                   |
| ------------------------ | ------------------------------------------- |
| `case`                 | 当前评测任务的序列化表示                    |
| `rubric`               | 完整 rubric 或 rubric metadata              |
| `rubric_question`      | 本次 Judge 只需要回答的独立问题             |
| `agent_output`         | 最终回答、研究报告，或序列化后的 trajectory |
| `trace_ref`            | 可选的 runtrace 引用                        |
| `artifact_ref`         | 可选的 artifact 引用                        |
| `deterministic_result` | 可选的 verifier/scorer 结果                 |
| `metadata`             | 输入来源、case ID、版本和实验标记           |

### 3.3 `QuestionJudgment`

Judge 输出结构：

```json
{
  "question_id": "...",
  "score": 0.0,
  "confidence": 0.0,
  "claims": [],
  "evidence_refs": [],
  "missing_evidence": [],
  "contradictions": [],
  "status": "supported"
}
```

其中：

- `score`：当前问题的连续分数，范围为 `0~1`；
- `confidence`：Judge 对自身判断的置信度；
- `claims`：Judge 的结构化判断；
- `evidence_refs`：被使用的 evidence ID；
- `missing_evidence`：Judge 认为缺失的证据；
- `contradictions`：发现的矛盾；
- `status`：`supported`、`partially_supported`、`unverified`、`contradictory` 等。

执行入口：

```text
judge/src/agentjudge/service.py:28
```

执行逻辑：

```text
JudgeRequest
→ 取出 rubric_question
→ 构造 Judge prompt
→ 创建 QuestionJudge agent
→ 注入 EvidenceProvider
→ LLM 输出 QuestionJudgment
→ 保存 score / claims / evidence_refs / status
```

---

## 4. AgentEval Core Runner 与 QuestionJudgeService 的区别

### 4.1 完整 Runner

定义位置：

```text
src/agenteval/runner.py
```

完整 Runner 的数据流：

```text
Case
→ Router.route()
→ 选择多个 skill
→ skill.prepare()
→ skill.evaluate()
→ SkillResult
→ CaseEvidence
→ cache/history/report
```

Runner 负责：

- skill routing；
- 多 skill 执行；
- 输入 digest；
- plan cache；
- skill result cache；
- history；
- evidence tree；
- run report。

### 4.2 单问题 Judge

定义位置：

```text
judge/src/agentjudge/service.py
```

QuestionJudgeService 只负责：

```text
一个 case
+ 一个 rubric question
+ 一个 agent output
→ 一个 QuestionJudgment
```

它不负责：

- benchmark-specific 数据 join；
- Gold accuracy 计算；
- 完整 AgentEval skill routing；
- 多问题聚合；
- cross-benchmark 报告；
- feedback routing。

### 4.3 当前 pilot 实际使用的层级

当前三个 pilot 的运行脚本直接调用：

```python
QuestionJudgeService(model, EvidenceCatalog([])).evaluate(request)
```

因此当前 pilot 的实际路径是：

```text
Benchmark-specific adapter
→ JudgeRequest
→ QuestionJudgeService
→ QuestionJudgment
→ 自定义 metrics
```

不是完整 Runner 路径。

这不是错误，而是一个有意的 Fast Loop：它避免重新运行 Harbor/Pi，也绕过不相关的完整任务编排，只测试 Judge 判断本身。

---

## 5. HealthBench 数据契约

### 5.1 Prompt-level OSS Eval 数据

文件：

```text
run/meta_eval/healthbench-gold-v1/source/healthbench.jsonl
```

典型结构：

```json
{
  "prompt_id": "...",
  "prompt": [
    {
      "role": "user",
      "content": "..."
    }
  ],
  "rubrics": [
    {
      "criterion": "...",
      "points": 10,
      "tags": ["axis:completeness"]
    }
  ],
  "example_tags": [...],
  "canary": "..."
}
```

它表达：

```text
一个用户问题
+ 多个 rubric criteria
```

它没有 assistant completion，所以不能单独用于 Judge accuracy。

它适合：

- RubricEval；
- prompt 分布分析；
- rubric 复杂度分析；
- HealthBench 任务抽样；
- 后续人工 Gold 设计。

### 5.2 Completion-level Meta-Eval 数据

文件：

```text
run/meta_eval/healthbench-gold-v1/source/healthbench_meta_eval.jsonl
```

典型结构：

```json
{
  "prompt_id": "...",
  "completion_id": "...",
  "prompt": [
    {
      "role": "user",
      "content": "..."
    }
  ],
  "completion": "...",
  "rubric": "...",
  "category": "...",
  "binary_labels": [true, false]
}
```

它表达：

```text
用户问题
+ candidate completion
+ 一个 rubric
+ 一个或多个 physician label
```

这是用于 AgentEval Judge accuracy 的 HealthBench 数据。

### 5.3 HealthBench 到 JudgeRequest 的映射

```text
HealthBench.prompt
→ JudgeRequest.case.prompt
```

```text
HealthBench.completion
→ JudgeRequest.agent_output
```

```text
HealthBench.rubric
→ JudgeRequest.rubric_question.question
```

```text
HealthBench.binary_labels
→ Gold reference
```

构造后的逻辑请求：

```json
{
  "case": {
    "case_id": "...",
    "prompt": [...],
    "task": "Judge the assistant completion against the supplied HealthBench rubric."
  },
  "rubric": {
    "rubric_id": "healthbench-meta-eval",
    "version": "2025-05-07",
    "criterion": "..."
  },
  "rubric_question": {
    "id": "healthbench_binary_criterion",
    "question": "...",
    "anchors": "0 = criterion not satisfied; 1 = criterion satisfied."
  },
  "agent_output": "assistant completion"
}
```

### 5.4 HealthBench Gold 的两种值

如果：

```json
"binary_labels": [true, true]
```

则：

```text
gold mean = 1.0
gold binary = true
```

如果：

```json
"binary_labels": [false, false]
```

则：

```text
gold mean = 0.0
gold binary = false
```

如果：

```json
"binary_labels": [true, false]
```

则：

```text
gold mean = 0.5
gold binary = true
```

因此必须同时保留：

```text
原始 reviewer labels
reviewer mean
majority binary
reviewer agreement
```

不能只保留一个 `gold_label`，否则会丢失人工不确定性。

### 5.5 HealthBench 当前 pilot 的边界

当前 HealthBench pilot：

```text
20 条 completion-level sample
+ 单 rubric
+ physician labels
```

结果：

```text
accuracy = 65%
```

它主要测试：

```text
Judge 能否根据 prompt + completion + rubric 做二元判断
```

它没有测试：

- 多 rubric criterion 的加权聚合；
- runtrace evidence；
- artifact evidence；
- runtime failure handling；
- AgentEval Router。

---

## 6. RuVerBench DeepResearch 数据契约

相关源文件：

```text
/home/yang/RuVerBench/data/benchmark/deepresearch_dataset.json
/home/yang/RuVerBench/data/benchmark/deepresearch_responses.json
/home/yang/RuVerBench/data/benchmark/deepresearch_labels.json
/home/yang/RuVerBench/data/benchmark/deepresearch_taxonomy.json
```

### 6.1 Dataset

```json
{
  "id": "DRB2_1",
  "question": "...",
  "rubric": [
    {
      "point": "..."
    }
  ]
}
```

一个 research task 下可以有多个 rubric point。

### 6.2 Response

```json
{
  "id": "DRB2_1",
  "question": "...",
  "response": "..."
}
```

通过：

```text
id
```

与 dataset join。

### 6.3 Label

```json
{
  "id": "DRB2_1",
  "result": {
    "coverage_results": [
      {
        "point": "...",
        "covered": true
      }
    ]
  }
}
```

通过：

```text
id + rubric point index
```

对齐 response、rubric 和 Gold。

### 6.4 Taxonomy

```text
format
numbers
logic
facts
```

taxonomy 主要用于：

- 抽样；
- 分类别 accuracy；
- 错误分析；
- 结果分层。

它不是当前 Judge 的额外证据。

### 6.5 DeepResearch 的实际 Judge 单位

当前 pilot 没有把完整 research report 压成一个总体分数，而是拆成：

```text
一个 response
+ 一个 rubric point
```

映射：

```text
DeepResearch.question
→ JudgeRequest.case.task
```

```text
DeepResearch.response
→ JudgeRequest.agent_output
```

```text
DeepResearch.rubric[].point
→ JudgeRequest.rubric_question.question
```

```text
DeepResearch.covered
→ Gold label
```

当前 pilot：

```text
accuracy = 85%
```

但它表示的是：

> Judge 在 20 个 response/rubric-point verification instance 上的准确率。

不是 20 个完整 research case 的总体准确率。

---

## 7. RuVerBench AgenticCoding 数据契约

相关源文件：

```text
/home/yang/RuVerBench/data/benchmark/agenticcoding_dataset.jsonl
/home/yang/RuVerBench/data/benchmark/agenticcoding_labels.json
/home/yang/RuVerBench/data/benchmark/agenticcoding_trajectories.jsonl
/home/yang/RuVerBench/data/benchmark/agenticcoding_taxonomy.json
```

### 7.1 Dataset

每个实例包含：

```json
{
  "instance_id": "...",
  "user_query": [...],
  "system_prompt": "...",
  "category": "...",
  "workspace_abs_path": "...",
  "scaffold": {...},
  "checklist": {
    "SP": {
      "description": "...",
      "checks": [
        {
          "check_id": "...",
          "description": "..."
        }
      ]
    }
  }
}
```

checklist 是嵌套结构，常见 section 包括：

```text
SP
Agents.md
Tool schema
System reminder
User query
```

### 7.2 Labels

```json
{
  "instance_id": "...",
  "SP": {
    "checks": [
      {
        "check_id": "...",
        "result": "success"
      }
    ]
  }
}
```

通过：

```text
instance_id + section + check_id
```

与 checklist item 对齐。

### 7.3 Trajectory

```json
{
  "meta": {
    "session_id": "..."
  },
  "tools": [...],
  "messages": [...]
}
```

通过：

```text
trajectory.meta.session_id = dataset.instance_id
```

和 coding task 对齐。

### 7.4 AgenticCoding 的实际 Judge 单位

当前 pilot 使用：

```text
一个 coding trajectory
+ 一个 checklist item
```

映射：

```text
AgenticCoding.user_query
→ JudgeRequest.case.user_query
```

```text
AgenticCoding.system_prompt
→ JudgeRequest.case.system_prompt
```

```text
AgenticCoding trajectory.messages
→ JudgeRequest.agent_output
```

```text
checklist.check.description
→ JudgeRequest.rubric_question.question
```

```text
check.result = success
→ gold_label = true
```

```text
check.result = fail
→ gold_label = false
```

当前 pilot：

```text
accuracy = 75%
```

它表示：

> Judge 对 20 个 coding trajectory/checklist verification instance 的判断准确率。

不是完整 coding task 的最终任务完成率。

---

## 8. 三个 benchmark 的统一适配抽象

三个 benchmark 的原始结构不同，但经过 adapter 后都被压缩成：

```text
一个 task/question
+ 一个 response 或 trajectory
+ 一个 rubric question
+ 一个 Gold label
```

统一数据流：

```text
Benchmark source
      ↓
benchmark-specific adapter
      ↓
JudgeRequest
      ↓
QuestionJudgeService
      ↓
QuestionJudgment
      ↓
score threshold
      ↓
Gold comparison
      ↓
metrics
```

更具体地说：

| Benchmark     | `case`                    | `agent_output`      | `rubric_question`       | Gold               |
| ------------- | --------------------------- | --------------------- | ------------------------- | ------------------ |
| HealthBench   | health prompt               | health completion     | HealthBench rubric string | physician majority |
| DeepResearch  | research question           | research report       | 一个 rubric point         | `covered`        |
| AgenticCoding | user query + system context | serialized trajectory | checklist description     | `success/fail`   |

---

## 9. 当前 pilot 的统一评分方式

当前三个 pilot 都做了以下转换：

```python
prediction_binary = prediction_score >= 0.5
```

然后与 Gold binary 比较。

### 9.1 Accuracy

```text
正确二元判断数 / 总判断数
```

衡量 Judge 最终分类是否正确。

### 9.2 Balanced Accuracy

```text
(True Positive Rate + True Negative Rate) / 2
```

当 Gold 正负类别不平衡时，比普通 accuracy 更可靠。

### 9.3 F1

当前使用的是正类 F1：

```text
precision 与 recall 的调和平均
```

它重点衡量 Judge 判断“满足 rubric”的质量。

### 9.4 Gold MAE

```text
mean(abs(Judge score - Gold reference score))
```

HealthBench 使用 physician label mean；RuVerBench 使用 `0/1` reference label。

### 9.5 当前 cross-benchmark 汇总

| Benchmark           |  N |    Acc | Balanced Acc |    F1 | Gold MAE |
| ------------------- | -: | -----: | -----------: | ----: | -------: |
| HealthBench         | 20 | 65.00% |       65.00% | 0.588 |   0.4043 |
| RuVer DeepResearch  | 20 | 85.00% |       83.33% | 0.800 |   0.1975 |
| RuVer AgenticCoding | 20 | 75.00% |       73.23% | 0.667 |   0.2500 |

结果文件：

```text
run/meta_eval/judge-cross-benchmark-summary-v1/cross-benchmark-metrics.json
run/meta_eval/judge-cross-benchmark-summary-v1/CROSS_BENCHMARK_JUDGE_META_EVAL.md
```

### 9.6 不能直接合并这些分数

三个 benchmark 的 Gold 语义和输入单位不同：

| 维度                 | HealthBench      | DeepResearch                 | AgenticCoding                |
| -------------------- | ---------------- | ---------------------------- | ---------------------------- |
| 输入                 | health response  | research response            | coding trajectory            |
| Gold                 | physician labels | coverage labels              | checklist labels             |
| 粒度                 | 单 rubric        | 单 point                     | 单 check                     |
| evidence             | response text    | response text                | 当前为 serialized trajectory |
| reviewer uncertainty | 有               | 通常无单独 reviewer 分歧字段 | 通常无单独 reviewer 分歧字段 |

所以这张表只能用于：

```text
跨域观察 Judge 的 pilot 表现
```

不能用于：

```text
计算 AgentEval 全局准确率
```

也不应简单将三行求平均。

---

## 10. 当前最重要的实现边界：EvidenceProvider

当前 pilot 的 Judge 初始化使用：

```python
EvidenceCatalog([])
```

即空 Evidence Catalog。

因此：

### HealthBench

Judge 主要依据：

```text
prompt + completion + rubric
```

这是 artifact/response-only 评估，基本符合该 benchmark 的输入形态。

### DeepResearch

Judge 主要依据：

```text
question + response + rubric point
```

同样属于 response-only 评估。

### AgenticCoding

Judge 目前看到的是：

```text
trajectory.messages 被序列化后的文本
```

而不是可自主检索的结构化 evidence。

因此当前 AgenticCoding 结果更准确的表述是：

> Judge 对 coding trajectory 文本的 checklist 判断准确率为 75%。

而不是：

> AgentEval 已经验证了 Judge 对 coding runtime evidence 的检索和判断能力。

---

## 11. AgenticCoding 结构化 evidence 的后续方向

如果要测试真正的 runtime evidence 能力，应把 trajectory 中的消息拆成 `EvidenceRecord`，例如：

```json
{
  "evidence_id": "msg-42",
  "source": "ruverbench.agenticcoding",
  "line": 42,
  "evidence_class": "direct_runtime_event",
  "claim_strength": "direct",
  "event_type": "tool_result",
  "tool_name": "pytest",
  "content": {
    "text": "...",
    "instance_id": "...",
    "check_id": "..."
  }
}
```

之后让 Judge：

```text
通过 evidence query 搜索相关 tool call / result / file change / test result
```

而不是：

```text
把整条 trajectory 直接放进 agent_output
```

这样才能分别测量：

- evidence retrieval recall；
- evidence applicability；
- tool result interpretation；
- trajectory order robustness；
- irrelevant evidence resistance；
- final checklist judgment accuracy。

---

## 12. 当前跨 benchmark 指标表的正确解释

### HealthBench：65%

表示：

```text
20 条 HealthBench completion-level sample 中，13 条 Judge binary decision 与 physician majority 一致。
```

### RuVer DeepResearch：85%

表示：

```text
20 个 research response/rubric-point instance 中，17 条 Judge binary decision 与 RuVerBench covered label 一致。
```

### RuVer AgenticCoding：75%

表示：

```text
20 个 coding trajectory/checklist instance 中，15 条 Judge binary decision 与 RuVerBench success/fail label 一致。
```

三者不是同一个问题的三个重复测量，而是三个不同输入域上的 Judge pilot。

---

## 13. 当前已经测到与尚未测到的内容

### 已经测到

- 单问题 Judge 是否返回合法 score；
- Judge 与外部 binary Gold 的一致率；
- 正负样本下的基础分类表现；
- 连续 score 与 Gold 的距离；
- 不同 benchmark domain 的初步错误分布；
- Judge service 的调用成功率。

### 尚未测到

- 多次重复 Judge 的一致率；
- score standard deviation；
- status stability；
- evidence order perturbation stability；
- trace length perturbation stability；
- irrelevant evidence robustness；
- AgentEval Router 是否选对 skill；
- 多 rubric question 的聚合正确率；
- AgenticCoding 结构化 evidence retrieval；
- artifact + runtime mixed evidence；
- deterministic verifier 与 Judge 分歧处理；
- 完整 AgentEval Runner 的 end-to-end Gold accuracy。

---

## 14. 从当前 pilot 到完整 meta-eval 的最小演进路径

### Phase 1：固定当前 20 条，做重复 replay

对每个 benchmark 的现有 20 条保持输入不变，进行 3 次 replay：

```text
20 cases × 3 repeats
```

记录：

- repeat binary agreement；
- score standard deviation；
- status agreement；
- per-category variance。

不需要运行 Harbor/Pi。

### Phase 2：增加 evidence perturbation

至少包含：

```text
none
order_shuffle
trace_lengthen
irrelevant_evidence_addition
```

记录：

```text
prediction unchanged / total perturbations
```

这一阶段用于测鲁棒性，不用于重新定义 Gold。

### Phase 3：结构化 AgenticCoding evidence

将 trajectory 消息转换为 EvidenceRecord，并比较：

```text
serialized trajectory input
vs
structured evidence retrieval input
```

保持：

- task；
- response；
- checklist；
- Gold；
- model；

不变。

### Phase 4：接入 AgentEval Core Runner

把 benchmark record 转换为：

```python
Case(
    case_id=...,
    task=...,
    expected=...,
    context=...,
    metadata=...
)
```

再运行：

```text
RunConfig
→ Router
→ SkillRegistry
→ MultiQuestionJudgeSkill
→ CaseEvidence
→ Gold comparison
```

只有这一步完成后，才可以正式报告：

```text
AgentEval overall meta-eval accuracy
```

---

## 15. 推荐统一的 Benchmark Adapter 输出

当前已经存在三个 pilot-specific 运行脚本，但尚未形成正式统一 adapter contract。建议后续只增加一个薄层，将各 benchmark 映射为如下内部记录：

```json
{
  "schema_version": "agenteval.meta_eval_instance.v1",
  "benchmark": "healthbench | ruverbench_deepresearch | ruverbench_agenticcoding",
  "domain": "health | research | coding",
  "case_id": "...",
  "task": "...",
  "agent_output": "...",
  "rubric_question": {
    "id": "...",
    "question": "...",
    "score_anchors": [
      {
        "score": 0.0,
        "label": "not_satisfied",
        "description": "..."
      },
      {
        "score": 1.0,
        "label": "satisfied",
        "description": "..."
      }
    ]
  },
  "evidence": {
    "mode": "none | response_only | structured_trace | mixed",
    "records": []
  },
  "gold": {
    "label_type": "physician_majority | coverage | checklist",
    "binary": true,
    "score": 1.0,
    "raw_labels": []
  },
  "provenance": {
    "source_file": "...",
    "source_id": "...",
    "rubric_id": "...",
    "point_id": "...",
    "input_digest": "..."
  }
}
```

这不是新的 benchmark schema，而是一个 benchmark-to-meta-eval 的薄适配层。它的作用是让：

```text
不同外部 benchmark
→ 同一个 AgentEval replay 入口
```

同时保留原始 Gold 类型和 provenance。

---

## 16. 结论

当前系统已经完成了三个不同 benchmark 到单问题 Judge 的接入：

```text
HealthBench
→ health response rubric judging
```

```text
RuVer DeepResearch
→ research response rubric-point verification
```

```text
RuVer AgenticCoding
→ coding trajectory checklist verification
```

统一交互方式为：

```text
benchmark record
→ JudgeRequest
→ QuestionJudgeService
→ QuestionJudgment
→ Gold comparison
```

当前 pilot 的结果是：

```text
HealthBench: 65%
RuVer DeepResearch: 85%
RuVer AgenticCoding: 75%
```

但这些结果严格来说是：

```text
single-question
single-replay
mostly text-based
Judge calibration pilot
```

下一阶段真正需要补的是：

1. 固定输入后的重复 replay；
2. evidence 顺序、长度和无关信息扰动；
3. AgenticCoding trajectory 的结构化 EvidenceRecord；
4. benchmark adapter 到 AgentEval Core Runner 的统一接入。

只有完成这些步骤后，才能把当前的三个 pilot 结果升级为对 AgentEval 整体正确性、稳定性和鲁棒性的系统性 meta-eval。
