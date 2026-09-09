# Agent Judge（PydanticAI 原型）

这是一个独立的、能够感知证据的 Judge 原型。它继承 HarnessEval-W 的以下流程：

```text
Planner → 问题子代理 → 父级校验 → 最终判断
```

项目使用 PydanticAI 承载子代理、工具和结构化输出；不依赖 AgentEval、
`eval-system`、Harbor 或 AgentOctagon 的内部模块。

## 开发

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

当前原型包含：

- `EvidenceRecord` / `Claim` / `QuestionJudgment`；
- `EvidenceProvider` 和 `EvidenceCatalog.from_attempt_dir()`；
- 过滤 streaming delta，并归一化 trace/wire/artifact；
- PydanticAI question/parent agent 工厂；
- `search_evidence`、`get_evidence`、`get_call_context`、`get_related_evidence` 工具；
- `QuestionJudgeService`：兼容路径，执行单个完整定义的 rubric question；
- `JointQuestionJudgeService`：生产 B 路径，一次调用联合判断一个 task 的全部 rubric questions。

HTTP service 已提供 `/v1/judge/evaluate`；生产默认使用 B（`JUDGE_PROTOCOL=B`），多 rubric 请求一次联合调用并返回逐题 judgments 与 overall score。单题请求仍兼容旧路径。

## 本地配置

将仓库根目录的 `.env.example` 复制为 `.env`，并填写 `JUDGE_API_KEY`。
独立服务器和 meta-evaluation runner 会自动加载这个被忽略的文件。凭据不会提交到
版本库；`.env.example` 只包含占位值。
