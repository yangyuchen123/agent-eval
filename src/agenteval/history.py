"""Evaluation history: append-only JSONL, queryable for rubric analysis.

Phase 2 of the layered plan (see docs/architecture.md). Every evaluated
(case, skill) writes one record:

    run_id, model_id, case_id, skill_id, rubric_id, rubric_version,
    score, subscores, status, judge, timestamp

JSONL (no database) keeps it dependency-free and machine-reviewable; the
query surface below is exactly what Phase 3 (rubric analysis) needs:

    by_skill / by_question / question_stats (discrimination) / ...
"""

from __future__ import annotations

import json
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .protocols import CaseEvidence

HISTORY_SCHEMA = "agenteval.history.v1"


def new_run_id(prefix: str = "run") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6]}"


@dataclass(frozen=True)
class EvalRecord:
    run_id: str
    model_id: str
    case_id: str
    skill_id: str
    score: float | None
    subscores: dict[str, float | None] = field(default_factory=dict)
    status: str = "ok"
    rubric_id: str | None = None
    rubric_version: str | None = None
    evaluator_version: str | None = None   # prompt/evaluator design version
    judge: str | None = None               # judge model
    judge_temperature: float | None = None
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": HISTORY_SCHEMA,
            "run_id": self.run_id,
            "model_id": self.model_id,
            "case_id": self.case_id,
            "skill_id": self.skill_id,
            "score": self.score,
            "subscores": self.subscores,
            "status": self.status,
            "rubric_id": self.rubric_id,
            "rubric_version": self.rubric_version,
            "evaluator_version": self.evaluator_version,
            "judge": self.judge,
            "judge_temperature": self.judge_temperature,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvalRecord":
        return cls(
            run_id=str(data.get("run_id") or ""),
            model_id=str(data.get("model_id") or ""),
            case_id=str(data.get("case_id") or ""),
            skill_id=str(data.get("skill_id") or ""),
            score=data.get("score"),
            subscores=dict(data.get("subscores") or {}),
            status=str(data.get("status") or "ok"),
            rubric_id=data.get("rubric_id"),
            rubric_version=data.get("rubric_version"),
            evaluator_version=data.get("evaluator_version"),
            judge=data.get("judge"),
            judge_temperature=data.get("judge_temperature"),
            timestamp=str(data.get("timestamp") or ""),
        )


def record_from_evidence(
    evidence: CaseEvidence, *, run_id: str, model_id: str,
    timestamp: str | None = None,
) -> list[EvalRecord]:
    """Flatten one CaseEvidence into one record per skill result."""
    stamp = timestamp or datetime.now(timezone.utc).isoformat()
    records = []
    for skill_id, result in evidence.skill_results.items():
        judge_diag = (result.diagnostics or {}).get("judge") or {}
        records.append(EvalRecord(
            run_id=run_id,
            model_id=model_id,
            case_id=evidence.case_id,
            skill_id=skill_id,
            score=result.score,
            subscores=result.subscores,
            status=result.status,
            rubric_id=judge_diag.get("rubric_id"),
            rubric_version=judge_diag.get("rubric_version"),
            evaluator_version=judge_diag.get("evaluator_version"),
            judge=judge_diag.get("model"),
            judge_temperature=judge_diag.get("temperature"),
            timestamp=stamp,
        ))
    return records


class HistoryStore:
    """Append-only JSONL writer + in-memory loader."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    # ------------------------------------------------------------ write ----
    def append(self, records: Iterable[EvalRecord]) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with open(self.path, "a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
                n += 1
        return n

    # ------------------------------------------------------------ read -----
    def load(self) -> list[EvalRecord]:
        if not self.path.is_file():
            return []
        rows = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(EvalRecord.from_dict(json.loads(line)))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
        return rows

    @staticmethod
    def load_many(paths: Iterable[str | Path]) -> list[EvalRecord]:
        merged: list[EvalRecord] = []
        for p in paths:
            merged.extend(HistoryStore(p).load())
        return merged


# ------------------------------------------------------------- queries -----

def by_skill(records: list[EvalRecord], skill_id: str) -> list[EvalRecord]:
    return [r for r in records if r.skill_id == skill_id]


def by_rubric(records: list[EvalRecord], rubric_id: str,
              version: str | None = None) -> list[EvalRecord]:
    out = [r for r in records if r.rubric_id == rubric_id]
    if version is not None:
        out = [r for r in out if r.rubric_version == version]
    return out


def question_values(records: list[EvalRecord], question_id: str) -> list[float]:
    """Scores of one rubric question across all records."""
    values = []
    for r in records:
        v = (r.subscores or {}).get(question_id)
        if v is not None and 0.0 <= v <= 1.0:
            values.append(float(v))
    return values


def question_stats(records: list[EvalRecord],
                   question_id: str) -> dict[str, Any]:
    """Discrimination statistics for one rubric question."""
    values = question_values(records, question_id)
    if len(values) < 2:
        return {"question_id": question_id, "n": len(values),
                "mean": None, "std": None, "min": None, "max": None,
                "variance": None, "discriminates": None}
    return {
        "question_id": question_id,
        "n": len(values),
        "mean": round(statistics.mean(values), 4),
        "std": round(statistics.pstdev(values), 4),
        "min": min(values),
        "max": max(values),
        "variance": round(statistics.pvariance(values), 4),
        # low std ⇒ everyone scores the same ⇒ no signal
        "discriminates": statistics.pstdev(values) > 0.05,
    }


def rubric_question_report(
    records: list[EvalRecord], rubric_id: str,
    version: str | None = None,
) -> dict[str, Any]:
    """Per-question discrimination report for a rubric (Phase 3 input)."""
    recs = by_rubric(records, rubric_id, version)
    # collect all question ids seen in subscores
    qids: list[str] = []
    for r in recs:
        for qid in (r.subscores or {}):
            if qid not in qids:
                qids.append(qid)
    questions = {qid: question_stats(recs, qid) for qid in qids}
    return {
        "rubric_id": rubric_id,
        "rubric_version": version,
        "n_records": len(recs),
        "n_questions": len(qids),
        "questions": questions,
        "n_low_discrimination": sum(
            1 for q in questions.values()
            if q.get("discriminates") is False),
    }


def summary_by_skill(records: list[EvalRecord]) -> dict[str, dict[str, Any]]:
    """Mean score per skill across records (quick overview)."""
    grouped: dict[str, list[float]] = {}
    for r in records:
        if r.score is None:
            continue
        grouped.setdefault(r.skill_id, []).append(float(r.score))
    return {
        skill: {"n": len(vals),
                "mean": round(statistics.mean(vals), 4),
                "std": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0}
        for skill, vals in sorted(grouped.items())
    }
