"""AgentEval core contracts.

This module defines the *domain-agnostic* data model. Nothing here knows
about any particular agent task: cases, skills, plans and results are all
described by plain dicts/JSON, so evaluation cases stay fully decoupled
from the framework.

Design lineage: the "agentified evaluation" idea (LLM router → skill
decomposition → evidence tree) is adapted from HarnessEval-W
(https://github.com/MirroS-Lab/HarnessEval-W, Apache-2.0).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["observation", "core", "diagnostic"]

CASE_SCHEMA = "agenteval.case.v1"
PLAN_SCHEMA = "agenteval.skill_plan.v1"
RESULT_SCHEMA = "agenteval.skill_result.v1"
EVIDENCE_SCHEMA = "agenteval.evidence_tree.v1"
REPORT_SCHEMA = "agenteval.report.v1"


# ------------------------------------------------------------- case -------

@dataclass(frozen=True)
class Case:
    """One evaluation instance.

    `task` is the input given to the agent under evaluation (prompt,
    environment state, ...). `expected` is optional ground truth used by
    skills that need it (golden answers, success criteria). `context` is
    optional evaluation-side resources (e.g. a price table the skills need
    to replay trajectories) — never exposed to the agent.
    """

    case_id: str
    task: str
    expected: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CASE_SCHEMA,
            "case_id": self.case_id,
            "task": self.task,
            "expected": self.expected,
            # context contains evaluator-only resources such as runtrace,
            # artifact manifests, and environment snapshots. It must be
            # serialized so evidence and cache digests reflect the full
            # evaluation input.
            "context": self.context,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Case":
        case_id = str(data.get("case_id") or "")
        if not case_id:
            raise ValueError("case requires case_id")
        return cls(
            case_id=case_id,
            task=str(data.get("task") or ""),
            expected=dict(data.get("expected") or {}),
            context=dict(data.get("context") or {}),
            metadata=dict(data.get("metadata") or {}),
        )


# ------------------------------------------------------------ skill -------

@dataclass(frozen=True)
class SkillSpec:
    """Static description of a skill, used by the router and the report.

    `question` is the applicability question the router answers with a
    case-grounded reason (exactly like HarnessEval's skill specs).
    """

    skill_id: str
    role: Role
    question: str
    core_for: tuple[str, ...] = ()       # optional task-family hints
    diagnostic_for: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "skill_id": self.skill_id,
            "role": self.role,
            "question": self.question,
        }
        if self.core_for:
            d["core_for"] = list(self.core_for)
        if self.diagnostic_for:
            d["diagnostic_for"] = list(self.diagnostic_for)
        return d


@dataclass(frozen=True)
class SkillResult:
    """A skill's verdict for one (case, agent output).

    `score` is in [0, 1]. `subscores` are named sub-question scores (the
    Q1..Qn decomposition) with `reasons` per key — the auditable part.
    `evidence` holds supporting artifacts (trajectory slices, raw model
    output, sampled frames...).
    """

    skill_id: str
    status: str                       # "ok" | "invalid" | "skipped" | "error"
    score: float | None               # None when the skill cannot judge
    subscores: dict[str, float | None] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RESULT_SCHEMA,
            "skill_id": self.skill_id,
            "status": self.status,
            "score": self.score,
            "subscores": self.subscores,
            "reasons": self.reasons,
            "evidence": self.evidence,
            "diagnostics": self.diagnostics,
        }


# ------------------------------------------------------------- plan -------

@dataclass(frozen=True)
class Plan:
    """Router output: which skills apply to a case, and why."""

    case_id: str
    selected_skills: tuple[dict[str, Any], ...]   # {skill_id, role, reason, parameters}
    skipped_skills: tuple[dict[str, Any], ...]    # {skill_id, reason}
    routing_mode: str = "rule"                    # "rule" | "llm"
    planner: dict[str, Any] = field(default_factory=dict)

    @property
    def selected_ids(self) -> tuple[str, ...]:
        return tuple(item["skill_id"] for item in self.selected_skills)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PLAN_SCHEMA,
            "case_id": self.case_id,
            "routing_mode": self.routing_mode,
            "selected_skills": list(self.selected_skills),
            "selected_skill_ids": list(self.selected_ids),
            "skipped_skills": list(self.skipped_skills),
            "planner": self.planner,
        }


# ---------------------------------------------------------- evidence ------

@dataclass(frozen=True)
class CaseEvidence:
    """Full auditable record for one case: plan + per-skill results."""

    case_id: str
    case: dict[str, Any]
    output: str                       # the agent output that was evaluated
    plan: Plan
    skill_results: dict[str, SkillResult] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EVIDENCE_SCHEMA,
            "case_id": self.case_id,
            "case": self.case,
            "output": self.output,
            "plan": self.plan.to_dict(),
            "skill_results": {
                k: v.to_dict() for k, v in sorted(self.skill_results.items())
            },
        }
