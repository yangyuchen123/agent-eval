"""Evaluation Run Manifest: the run-level entity.

Every evaluation produces, next to history.jsonl, a run_manifest.json that
records *under what conditions the report was produced*:

    run_id, agent (name/version), environment (date/machine/python),
    benchmarks, evaluator_snapshot (rubric versions + judge models seen
    in this run's history)

Industrial question this answers: "can I trust this report? what exactly
was evaluated, by which judge, with which rubric versions, when?"
"""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .history import EvalRecord, HistoryStore

MANIFEST_SCHEMA = "agenteval.run_manifest.v1"


@dataclass(frozen=True)
class EvaluationRun:
    run_id: str
    agent: dict[str, str] = field(default_factory=dict)        # name/version
    environment: dict[str, str] = field(default_factory=dict)  # date/machine/...
    benchmarks: tuple[str, ...] = ()
    evaluator_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MANIFEST_SCHEMA,
            "run_id": self.run_id,
            "agent": dict(self.agent),
            "environment": dict(self.environment),
            "benchmarks": list(self.benchmarks),
            "evaluator_snapshot": dict(self.evaluator_snapshot),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvaluationRun":
        return cls(
            run_id=str(data.get("run_id") or ""),
            agent=dict(data.get("agent") or {}),
            environment=dict(data.get("environment") or {}),
            benchmarks=tuple(str(b) for b in (data.get("benchmarks") or ())),
            evaluator_snapshot=dict(data.get("evaluator_snapshot") or {}),
        )


def current_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = {
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "machine": platform.node(),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    if extra:
        env.update(extra)
    return env


def evaluator_snapshot(records: Iterable[EvalRecord]) -> dict[str, Any]:
    """Rubric/judge versions observed in a run's history records."""
    rubric_versions: dict[str, set[str]] = {}
    judges: set[str] = set()
    evaluators: set[str] = set()
    for r in records:
        if r.rubric_id and r.rubric_version:
            rubric_versions.setdefault(r.rubric_id, set()).add(r.rubric_version)
        if r.judge:
            judges.add(r.judge)
        if r.evaluator_version:
            evaluators.add(r.evaluator_version)
    return {
        "rubric_versions": {k: sorted(v) for k, v in rubric_versions.items()},
        "judge_models": sorted(judges),
        "evaluator_versions": sorted(evaluators),
    }


def write_manifest(run_root: str | Path, run: EvaluationRun) -> Path:
    run_root = Path(run_root)
    path = run_root / "run_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(run.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return path


def load_manifest(run_root: str | Path) -> EvaluationRun:
    data = json.loads((Path(run_root) / "run_manifest.json")
                      .read_text(encoding="utf-8"))
    return EvaluationRun.from_dict(data)


def build_manifest(
    run_id: str,
    history: HistoryStore,
    *,
    agent_name: str = "unknown",
    agent_version: str = "",
    benchmarks: Iterable[str] = (),
    extra_environment: Mapping[str, str] | None = None,
) -> EvaluationRun:
    records = history.load()
    return EvaluationRun(
        run_id=run_id,
        agent={"name": agent_name, "version": agent_version},
        environment=current_environment(extra_environment),
        benchmarks=tuple(benchmarks),
        evaluator_snapshot=evaluator_snapshot(records),
    )
