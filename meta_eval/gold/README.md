# Human Gold Calibration Set

This directory is intentionally empty until a human reviews each case. Do not
copy deterministic scorer outputs or previous LLM judgments into this
目录并把它们当作 Gold。

每个 JSON 文件应遵循 `agenteval.meta_eval.GoldJudgment` schema，例如：

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

没有人工确认的 judgment 不得作为 Gold 使用。
