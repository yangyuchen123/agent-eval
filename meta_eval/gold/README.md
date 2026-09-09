# 人工 Gold 校准集

在人工审核每个案例之前，该目录应保持为空。不得将 deterministic scorer 的输出或
之前的 LLM judgment 复制到这里，并把它们当作 Gold。

每个 JSON 文件都应遵循 `agenteval.meta_eval.GoldJudgment` schema，例如：

```json
{
  "case_id": "...",
  "question_id": "coordination_and_handoff_quality",
  "expected_score": 0.5,
  "expected_status": "partially_supported",
  "positive_evidence_refs": ["trace.jsonl:35"],
  "negative_evidence_refs": [],
  "required_evidence_refs": ["trace.jsonl:35"],
  "missing_evidence": ["direct downstream consumption event"],
  "notes": "human reviewer and review date"
}
```

未经人工确认的 judgment 不得作为 Gold 使用。
