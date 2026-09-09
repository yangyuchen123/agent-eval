"""Named Judge protocols used by experiments.

Experiment runners should select one of these implementations by name. The
protocol logic belongs in the Judge module; runners should only load frozen
inputs, call ``evaluate`` and persist results.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from .catalog import EvidenceCatalog
from .models import JudgeRequest, JointQuestionJudgment, QuestionJudgment
from .service import JointQuestionJudgeService, QuestionJudgeService
from .two_stage import EvidenceCollection, EvidenceThenPerQuestionJudgeService, TwoStageJointJudgeService


@dataclass
class ProtocolResult:
    judgments: list[QuestionJudgment]
    evidence: EvidenceCollection | None = None
    status: str = "scored"
    overall_score: float | None = None

    def score_mean(self) -> float:
        if self.overall_score is not None:
            return self.overall_score
        return sum(j.score for j in self.judgments) / len(self.judgments) if self.judgments else 0.0


class JudgeProtocol:
    name: str
    expected_model_calls: str

    async def evaluate(self, *, task: Any, questions: list[dict[str, Any]], agent_output: str) -> ProtocolResult:
        raise NotImplementedError


class OriginalIndependentRubricProtocol(JudgeProtocol):
    """A: original QuestionJudge, one criterion per call, full trajectory."""

    name = "A_original_independent_rubric"
    expected_model_calls = "one_per_criterion"

    def __init__(self, model: Any):
        self.model = model

    async def evaluate(self, *, task: Any, questions: list[dict[str, Any]], agent_output: str) -> ProtocolResult:
        service = QuestionJudgeService(self.model, EvidenceCatalog([]))
        judgments: list[QuestionJudgment] = []
        for question in questions:
            request = JudgeRequest(
                case={"task": __import__("json").dumps(task, ensure_ascii=False)},
                rubric={"questions": [question]},
                rubric_question=question,
                agent_output=agent_output,
                metadata={"protocol": "agent-eval.abcd.frozen.v1", "condition": "A"},
            )
            judgments.append(await service.evaluate(request))
        return ProtocolResult(judgments=judgments)


class JointMultiRubricProtocol(JudgeProtocol):
    """B: one full-trajectory joint call per task."""

    name = "B_joint_multi_rubric"
    expected_model_calls = "one_per_task"

    def __init__(self, model: Any):
        self.model = model

    async def evaluate(self, *, task: Any, questions: list[dict[str, Any]], agent_output: str) -> ProtocolResult:
        request = JudgeRequest(
            case={"task": __import__("json").dumps(task, ensure_ascii=False)},
            rubric={"questions": questions},
            agent_output=agent_output,
            metadata={"protocol": "agent-eval.abcd.frozen.v1", "condition": "B"},
        )
        result: JointQuestionJudgment = await JointQuestionJudgeService(self.model, EvidenceCatalog([])).evaluate(request)
        return ProtocolResult(judgments=result.question_judgments, status=result.status, overall_score=result.overall_score)


class SharedEvidenceJointProtocol(JudgeProtocol):
    """C: one evidence packet, then one joint score call."""

    name = "C_shared_evidence_joint_score"
    expected_model_calls = "one_evidence_plus_one_score_per_task"

    def __init__(self, model: Any):
        self.service = TwoStageJointJudgeService(model)

    async def evaluate(self, *, task: Any, questions: list[dict[str, Any]], agent_output: str) -> ProtocolResult:
        evidence, result = await self.service.evaluate(task=task, questions=questions, agent_output=agent_output)
        return ProtocolResult(judgments=result.question_judgments, evidence=evidence, status=result.status, overall_score=result.overall_score)


class SharedEvidenceIndependentScoreProtocol(JudgeProtocol):
    """D: one shared evidence packet, then one score call per criterion."""

    name = "D_shared_evidence_independent_score"
    expected_model_calls = "one_evidence_per_task_plus_one_score_per_criterion"

    def __init__(self, model: Any):
        self.service = EvidenceThenPerQuestionJudgeService(model)

    async def evaluate(self, *, task: Any, questions: list[dict[str, Any]], agent_output: str) -> ProtocolResult:
        evidence, judgments = await self.service.evaluate_per_question(task=task, questions=questions, agent_output=agent_output)
        return ProtocolResult(judgments=judgments, evidence=evidence)


_PROTOCOLS = {
    "A": OriginalIndependentRubricProtocol,
    "B": JointMultiRubricProtocol,
    "C": SharedEvidenceJointProtocol,
    "D": SharedEvidenceIndependentScoreProtocol,
}


def build_protocol(condition: str, model: Any) -> JudgeProtocol:
    try:
        return _PROTOCOLS[condition](model)
    except KeyError as exc:
        raise ValueError(f"unknown frozen Judge condition: {condition!r}; expected A/B/C/D") from exc


def protocol_names() -> dict[str, str]:
    return {key: cls.name for key, cls in _PROTOCOLS.items()}
