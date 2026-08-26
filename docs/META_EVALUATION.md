# AgentEval Meta-Evaluation / Judge Reliability

本阶段冻结普通 benchmark 的 rubric、Judge policy 和 Evidence Layer，新增
独立的可靠性验证层：

```text
gold judgment + frozen evidence snapshot
          ↓
repeated / order / distractor / length / removal / paraphrase experiments
          ↓
retrieval + claim + score + stability metrics
          ↓
reproducible judgments.jsonl / failures.jsonl / metrics.json / report
```

## 目录与接口

```text
src/agenteval/meta_eval/
  gold.py          # human GoldJudgment
  taxonomy.py      # R1-R12 failure taxonomy
  perturbations.py # deterministic EvidenceSnapshot transforms
  metrics.py       # retrieval, claim, score, stability metrics
  runner.py        # replayable experiment runner
  baselines.py     # explicit Full-Trace / Static / Agentic boundaries
  report.py        # META_EVAL_REPORT.md
meta_eval/gold/    # human-maintained Gold only
```

`MetaEvalRunner` 不参与普通 `AgentEval` scoring，也不改变 Judge 结论。每条
observation 都保存 trace/artifact digest、snapshot digest、judge config、扰动
seed、query trajectory、evidence refs、claims、latency 和 failure labels。

## 运行真实 Agentic Judge

必须先设置真实模型配置；脚本在缺少 key 时会直接退出，不能用 TestModel 冒充
真实结果：

```bash
source judge/.venv/bin/activate
export JUDGE_BASE_URL=https://llm2.yangl.com.cn/v1
export JUDGE_MODEL=gpt-5.6-luna
export JUDGE_API_KEY=...
PYTHONPATH=src:judge/src python tools_run_meta_eval.py
```

当前 `agent-octagon` 已提供 352 个带 trace 的真实 attempt、84 个 env、49 个
同 task 重复组。`tools_build_octagon_calibration.py` 可以生成候选清单，但它
不会自动生成 Gold；达到第一阶段标准前，仍需要人工从这些真实 attempt 中审阅
并加入至少 30 个 question-level Gold JSON，同时显式提供 Full-Trace 和 Static
Retrieval judge 的实际实现/服务配置。

## Gold 原则

Gold 必须由人工写出：

```text
question → expected claim/status → positive/negative/required evidence → score
```

不能把 deterministic scorer 或既有 LLM Judge 输出直接当作 Gold。Gold 不完整
时，指标输出 `unavailable`，而不是伪造 agreement。

## `.env` 配置

项目会自动读取仓库根目录的本地 `.env`，且不会覆盖已经存在的环境变量：

```bash
cp .env.example .env
# 编辑 .env，填入 JUDGE_API_KEY
```

`.env` 已加入 `.gitignore`，`.env.example` 会被提交。Judge server 和
`tools_run_meta_eval.py` 都会自动加载该文件，因此不再需要每次手动
`export`。

## 细粒度离散评分锚点

三模式实验发现，Judge 即使引用相同 evidence，也会因为把多个过程要素捆在一个
连续总分中而产生不同权重解释。新的可靠性协议因此使用：

```text
一个独立计分维度
→ 一个独立 QuestionJudge
→ 一组简洁、离散、可观察的 score_anchors
→ AgentEval 加权聚合
```

结构示例：

```json
{
  "id": "result_validation",
  "question": "Did the agent perform task-appropriate validation?",
  "score_anchors": [
    {"score": 0.0, "label": "unsupported", "description": "No validation, or validation contradicts the result."},
    {"score": 0.5, "label": "partial", "description": "Some material outcomes remain unverified."},
    {"score": 1.0, "label": "supported", "description": "Every material outcome required by the task contract is directly checked."}
  ],
  "evidence": "Cite direct validation events and results.",
  "weight": 1.0
}
```

设计边界：

- `score_anchors` 是 rubric 数据，不是 Judge 内部硬编码规则；
- Judge 仍自主搜索和解释 evidence；
- 声明结构化 anchors 的 question 必须选择其中一个分数，不能返回 `0.86` 之类
  临场连续分数；
- 旧的自由文本 `anchors` 继续兼容，但不会自动启用严格离散校验；
- 不通过把总分直接 snap 到最近档位掩盖 reasoning；离散选择发生在每个独立
  QuestionJudge 内；
- 总分仍由 AgentEval 根据显式 `weight` 聚合，所以不同维度的贡献可追溯。

当前 runtime-process rubric v3（v2 实验版本保留用于 replay）拆为五个独立维度：

```text
task_understanding
required_action_execution
result_validation
observed_failure_handling
completion_claim_integrity
```

每个维度使用 `0 / 0.5 / 1` 三档简洁锚点。旧的 `generic_process_evidence_quality` bundled question 和离散 v2 结果都保留用于历史审计。当前 v3 进一步把 failure handling 限定为显式、Agent 可见的 operation/check failure signal；不同版本的聚合分数不能直接视为同一协议。

运行真实 batch 时可以通过以下配置限制问题范围，避免无意扩大调用量：

```bash
META_EVAL_QUESTION_IDS=result_validation,completion_claim_integrity
```
