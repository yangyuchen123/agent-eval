"""Data models for the RRD rubric optimizer.

The core models intentionally do not contain AgentEval taxonomy semantics.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

@dataclass(frozen=True)
class Rubric:
    rubric_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], index: int = 0) -> "Rubric":
        rid = str(value.get("rubric_id") or value.get("criterion_id") or value.get("id") or f"R{index + 1}")
        text = str(value.get("text") or value.get("criterion") or "").strip()
        metadata = {str(k): v for k, v in value.items() if k not in {"rubric_id", "criterion_id", "id", "text", "criterion"}}
        return cls(rid, text, metadata)
    def to_dict(self) -> dict[str, Any]:
        return {"rubric_id": self.rubric_id, "text": self.text, **self.metadata}

@dataclass(frozen=True)
class CalibrationResponse:
    response_id: str
    quality_group: str
    response: str
    metadata: dict[str, Any] = field(default_factory=dict)
    artifact_paths: tuple[str, ...] = ()
    artifact_status: str = "not_applicable"
    artifact_text: str = ""
    agent_prose: str = ""
    runtrace: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], index: int = 0) -> "CalibrationResponse":
        rid = str(value.get("response_id") or value.get("id") or f"response_{index + 1}")
        group = str(value.get("quality_group") or value.get("group") or "").lower()
        if group not in {"strong", "middle", "weak"}:
            raise ValueError(f"response {rid} must have quality_group strong, middle, or weak")
        text = str(value.get("response") or value.get("text") or "")
        nested: dict[str, Any] = {}
        if text.strip().startswith("{"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                nested = parsed
        from .artifacts import collect_artifact_paths
        paths = tuple(collect_artifact_paths(dict(value), nested))
        agent_prose = str(value.get("agent_prose") or nested.get("final_agent_response") or "")
        runtrace = str(value.get("runtrace") or "")
        metadata = {str(k): v for k, v in value.items() if k not in {
            "response_id", "id", "quality_group", "group", "response", "text",
            "artifact_paths", "agent_prose", "runtrace",
        }}
        status = "empty" if not paths else "declared"
        return cls(rid, group, text, metadata, paths, status, "", agent_prose, runtrace)

    def with_artifacts(self, artifact_text: str, status: str) -> "CalibrationResponse":
        return replace(self, artifact_text=artifact_text, artifact_status=status)

@dataclass
class RubricMetric:
    support_rate: float
    strong_support_rate: float
    weak_support_rate: float
    middle_support_rate: float | None
    discrimination: float
    support_count: int
    strong_count: int
    weak_count: int
    broad_candidate: bool = False
    misalignment_candidate: bool = False
    def to_dict(self) -> dict[str, Any]:
        return {
            "support_rate": round(self.support_rate, 6),
            "strong_support_rate": round(self.strong_support_rate, 6),
            "middle_support_rate": None if self.middle_support_rate is None else round(self.middle_support_rate, 6),
            "weak_support_rate": round(self.weak_support_rate, 6),
            "discrimination": round(self.discrimination, 6),
            "support_count": self.support_count,
            "strong_count": self.strong_count,
            "weak_count": self.weak_count,
            "broad_candidate": self.broad_candidate,
            "misalignment_candidate": self.misalignment_candidate,
        }

@dataclass
class OptimizationConfig:
    # Faithful RRD broadness gate: satisfied by more than N samples.
    broad_satisfied_count_threshold: int = 2
    # Kept as a diagnostic/compatibility field, not used by broadness.
    broad_support_threshold: float = .75
    low_discrimination_threshold: float = .25
    misalignment_margin: float = 0.0
    behavioral_agreement_threshold: float = .90
    semantic_similarity_threshold: float = .92
    max_children_per_rubric: int = 3
    max_decomposition_depth: int = 2
    max_iterations: int = 2
    # 0 or None disables the expansion cap.
    max_total_expansion_ratio: float | None = 1.5
    min_children: int = 2
    enable_semantic_filter: bool = True
    enable_misalignment_filter: bool = True
    enable_behavioral_warnings: bool = True
    # None = count every evaluated response. GDPval should set ("strong",).
    broadness_quality_groups: tuple[str, ...] | None = None
    require_artifact: bool = False
    include_runtrace: bool = False
    include_agent_prose: bool = True
    include_quality_group_in_prompt: bool = False
    response_batch_size: int = 3
    def to_dict(self): return dict(self.__dict__)

    def broadness_groups(self) -> tuple[str, ...] | None:
        return self.broadness_quality_groups

@dataclass
class DecompositionProposal:
    parent_rubric_id: str
    children: list[Rubric]
    reason: str = ""
    status: str = "proposed"

@dataclass
class OptimizationResult:
    task_id: str
    initial_rubrics: list[Rubric]
    optimized_rubrics: list[Rubric]
    rubric_metrics: dict[str, RubricMetric]
    satisfaction_matrix: dict[str, dict[str, int]]
    decomposition_tree: dict[str, Any]
    dropped_rubrics: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    rubric_weights: dict[str, float] = field(default_factory=dict)
    behavioral_warnings: list[dict[str, Any]] = field(default_factory=list)
    round_snapshots: list[dict[str, Any]] = field(default_factory=list)
    def to_dict(self):
        return {
            "task_id": self.task_id,
            "initial_rubric_count": len(self.initial_rubrics),
            "final_rubric_count": len(self.optimized_rubrics),
            "optimized_rubrics": [r.to_dict() for r in self.optimized_rubrics],
            "decomposition_tree": self.decomposition_tree,
            "dropped_rubrics": self.dropped_rubrics,
            "rubric_metrics": {k:v.to_dict() for k,v in self.rubric_metrics.items()},
            "satisfaction_matrix": self.satisfaction_matrix,
            "rubric_weights": self.rubric_weights,
            "behavioral_warnings": self.behavioral_warnings,
            "round_snapshots": self.round_snapshots,
            "optimization_trace": self.trace,
        }
