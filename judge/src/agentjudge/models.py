"""Versioned Judge request, evidence and structured judgment models."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


EvidenceClass = Literal[
    "direct_runtime_event",
    "derived_runtime_relation",
    "artifact_observation",
    "retrospective_artifact",
]
ClaimStatus = Literal["supported", "partially_supported", "unverified", "contradictory"]


class JudgeRequest(BaseModel):
    schema_version: Literal["agenteval.judge_request.v1"] = "agenteval.judge_request.v1"
    case: dict[str, Any]
    rubric: Any
    rubric_question: dict[str, Any] = Field(default_factory=dict)
    agent_output: str
    trace_ref: Any = None
    artifact_ref: Any = None
    deterministic_result: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceRecord(BaseModel):
    evidence_id: str
    source: str
    line: int | None = None
    # Runtime-neutral names. The legacy names remain for compatibility with
    # existing fixtures and callers.
    event_type: str | None = None
    kind: str | None = None
    evidence_class: EvidenceClass
    claim_strength: Literal["direct", "derived", "indirect"]
    actor_agent_id: str | None = None
    target_agent_id: str | None = None
    agent_id: str | None = None
    parent_agent_id: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    message_id: str | None = None
    timestamp: str | None = None
    file_path: str | None = None
    lifecycle_state: str | None = None
    content: dict[str, Any] = Field(default_factory=dict)
    related_evidence: list[str] = Field(default_factory=list)


class EvidenceQuery(BaseModel):
    """Generic runtime search, intentionally free of rubric semantics."""

    text: str | None = None
    source: str | None = None
    event_type: list[str] = Field(default_factory=list)
    # kind is retained as a compatibility alias for old callers.
    kind: list[str] = Field(default_factory=list)
    tool_name: str | None = None
    agent_id: str | None = None
    parent_agent_id: str | None = None
    target_agent_id: str | None = None
    tool_call_id: str | None = None
    message_id: str | None = None
    before: str | None = None
    after: str | None = None
    limit: int = Field(default=12, ge=1, le=30)


class Claim(BaseModel):
    claim_id: str
    statement: str
    status: ClaimStatus
    evidence_refs: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class QuestionJudgment(BaseModel):
    question_id: str
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    claims: list[Claim] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    status: ClaimStatus


class FinalJudgment(BaseModel):
    schema_version: Literal["agentjudge.final_judgment.v1"] = "agentjudge.final_judgment.v1"
    score: float | None = Field(default=None, ge=0, le=1)
    subscores: dict[str, float | None] = Field(default_factory=dict)
    reasons: dict[str, str] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)
    question_judgments: list[QuestionJudgment] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["scored", "incomplete_evidence", "incompatible_input_contract", "judge_error"]

class JointQuestionJudgment(BaseModel):
    """One model call judging all rubric questions for a task."""
    schema_version: Literal["agentjudge.joint_judgment.v1"] = "agentjudge.joint_judgment.v1"
    question_judgments: list[QuestionJudgment] = Field(default_factory=list)
    overall_score: float = Field(ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: Literal["scored", "incomplete_evidence", "judge_error"] = "scored"


class CompactQuestionJudgment(BaseModel):
    """One-shot B output: score plus a short reason, no claim/evidence objects."""
    question_id: str
    score: float = Field(ge=0, le=1)
    reason: str = ""
    status: ClaimStatus = "supported"


class CompactJointJudgment(BaseModel):
    schema_version: Literal["agentjudge.joint_judgment.compact.v1"] = "agentjudge.joint_judgment.compact.v1"
    question_judgments: list[CompactQuestionJudgment] = Field(default_factory=list)
    overall_score: float = Field(ge=0, le=1)
    status: Literal["scored", "incomplete_evidence", "judge_error"] = "scored"

    def to_joint_judgment(self) -> JointQuestionJudgment:
        rows = [
            QuestionJudgment(
                question_id=item.question_id,
                score=item.score,
                confidence=1.0,
                claims=([Claim(claim_id=f"{item.question_id}.r", statement=item.reason, status=item.status)] if item.reason else []),
                evidence_refs=[],
                missing_evidence=[],
                contradictions=[],
                status=item.status,
            )
            for item in self.question_judgments
        ]
        return JointQuestionJudgment(
            question_judgments=rows,
            overall_score=self.overall_score,
            confidence=None,
            status=self.status,
        )
