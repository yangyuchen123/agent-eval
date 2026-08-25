# Agent Judge (PydanticAI prototype)

独立的 evidence-aware Judge 原型。它继承 HarnessEval-W 的：

```text
Planner → question subagents → parent validation → final judgment
```

使用 PydanticAI 承载 subagent、tools 和 structured output；不依赖 AgentEval、
eval-system、Harbor 或 AgentOctagon 的内部模块。

## 开发

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

当前原型包含：

- `EvidenceRecord` / `Claim` / `QuestionJudgment`；
- `EvidenceProvider` 和 `EvidenceCatalog.from_attempt_dir()`；
- 过滤 streaming delta 的 trace/wire/artifact 归一化；
- PydanticAI question/parent agent factory；
- `search_evidence`、`get_evidence`、`get_call_context`、`get_related_evidence` tools；
- `QuestionJudgeService`：执行单个 fully-specified rubric question；

HTTP service、真实 runtime provider 和完整 claim policy 在后续阶段加入。
