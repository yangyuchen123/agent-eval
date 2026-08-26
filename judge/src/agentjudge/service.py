"""Single-question Judge subagent service."""
from __future__ import annotations

import json
import dataclasses
from typing import Any

from .agents import QuestionJudgeDeps, build_question_agent
from .evidence import EvidenceProvider
from .models import JudgeRequest, QuestionJudgment


class QuestionJudgeService:
    """Execute one fully specified rubric question with PydanticAI.

    The service does not plan evidence queries. ``last_query_trajectory`` is
    diagnostic provenance used to distinguish a search-environment failure
    from a Judge that simply stopped investigating.
    """

    def __init__(self, model: Any, evidence: EvidenceProvider):
        self.model = model
        self.evidence = evidence
        self.last_query_trajectory: list[dict[str, Any]] = []
        self.last_usage: dict[str, Any] | None = None
        self.last_scoring_provenance: dict[str, Any] = {}

    async def evaluate(self, request: JudgeRequest) -> QuestionJudgment:
        question = request.rubric_question or _question_from_rubric(request.rubric)
        agent = build_question_agent(self.model)
        result = await agent.run(
            _question_prompt(request, question),
            deps=QuestionJudgeDeps(question=question, evidence=self.evidence),
        )
        trajectory = getattr(self.evidence, "query_trajectory", None)
        self.last_query_trajectory = list(trajectory()) if callable(trajectory) else []
        usage = getattr(result, "usage", None)
        self.last_usage = dataclasses.asdict(usage) if usage is not None and dataclasses.is_dataclass(usage) else None
        if self.last_usage and self.last_usage.get("cost") is not None:
            self.last_usage["cost"] = str(self.last_usage["cost"])
        anchors = [
            dict(anchor) for anchor in (question.get("score_anchors") or [])
            if isinstance(anchor, dict) and anchor.get("score") is not None
        ]
        selected = next(
            (anchor for anchor in anchors if abs(float(anchor["score"]) - result.output.score) <= 1e-9),
            None,
        )
        self.last_scoring_provenance = {
            "scoring_mode": "discrete_anchor" if anchors else "continuous_legacy",
            "declared_score_anchors": anchors,
            "selected_anchor": selected,
            "selected_score": result.output.score,
        }
        return result.output


JudgeService = QuestionJudgeService


def _question_from_rubric(rubric: Any) -> dict[str, Any]:
    if isinstance(rubric, dict):
        questions = rubric.get("questions") or rubric.get("rubric_questions") or []
        if questions and isinstance(questions[0], dict):
            return dict(questions[0])
    return {"id": "overall", "question": "Judge the case against the supplied rubric."}


def _question_prompt(request: JudgeRequest, question: dict[str, Any]) -> str:
    score_anchors = [
        anchor for anchor in (question.get("score_anchors") or [])
        if isinstance(anchor, dict) and anchor.get("score") is not None
    ]
    instruction = (
        "Investigate autonomously with generic evidence tools; cite evidence_id "
        "and mark unsupported claims unverified."
    )
    if score_anchors:
        allowed = ", ".join(str(anchor["score"]) for anchor in score_anchors)
        instruction += (
            f" Select exactly one declared score anchor ({allowed}); do not invent "
            "an intermediate continuous score. Apply only this question's concise "
            "anchor descriptions and use the selected anchor score as the final score."
        )
    return json.dumps({
        "task": request.case.get("task") if isinstance(request.case, dict) else request.case,
        "question": question,
        "agent_output": request.agent_output,
        "trace_ref": request.trace_ref,
        "artifact_ref": request.artifact_ref,
        "deterministic_result": request.deterministic_result,
        "instruction": instruction,
    }, ensure_ascii=False)
