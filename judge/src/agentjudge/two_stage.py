"""Two-stage joint judging: evidence collection separated from scoring."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from .models import JointQuestionJudgment


class EvidenceItem(BaseModel):
    evidence_id: str
    question_id: str
    excerpt: str
    relevance: str
    polarity: str = "neutral"


class EvidenceCollection(BaseModel):
    schema_version: str = "agentjudge.evidence_collection.v1"
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    missing_evidence: dict[str, list[str]] = Field(default_factory=dict)
    status: str = "collected"


class TwoStageJointJudgeService:
    """Collect evidence first, then score all rubric questions jointly.

    The collector is forbidden to output scores. The scorer receives only the
    frozen evidence packet and cannot perform additional evidence search.
    """

    def __init__(self, model: Any):
        self.model = model

    async def collect(self, *, task: Any, questions: list[dict[str, Any]], agent_output: str) -> EvidenceCollection:
        agent = Agent(
            self.model,
            output_type=EvidenceCollection,
            system_prompt=(
                "You are an evidence collector, not a judge. For every supplied rubric "
                "question, find only directly relevant excerpts in the task response or "
                "trajectory. Do not assign scores, labels, or pass/fail conclusions. "
                "Use stable ids E1, E2, ... and record missing evidence explicitly."
            ),
        )
        prompt = json.dumps({
            "task": task,
            "rubric_questions": questions,
            "agent_output_or_trajectory": agent_output,
            "instruction": "Return evidence packets only; never score a question.",
        }, ensure_ascii=False)
        return (await agent.run(prompt)).output

    async def score(self, *, task: Any, questions: list[dict[str, Any]], evidence: EvidenceCollection) -> JointQuestionJudgment:
        agent = Agent(
            self.model,
            output_type=JointQuestionJudgment,
            system_prompt=(
                "You are a scoring judge. Score every rubric question using only the "
                "frozen evidence packet. Do not search, add evidence, or infer facts "
                "not present in the packet. Apply each question's own anchors independently. "
                "Return exactly one judgment per question in input order and set "
                "overall_score to the unweighted mean."
            ),
        )
        prompt = json.dumps({
            "task": task,
            "rubric_questions": questions,
            "frozen_evidence_packet": evidence.model_dump(),
        }, ensure_ascii=False)
        return (await agent.run(prompt)).output

    async def evaluate(self, *, task: Any, questions: list[dict[str, Any]], agent_output: str) -> tuple[EvidenceCollection, JointQuestionJudgment]:
        evidence = await self.collect(task=task, questions=questions, agent_output=agent_output)
        score = await self.score(task=task, questions=questions, evidence=evidence)
        return evidence, score

class EvidenceThenPerQuestionJudgeService(TwoStageJointJudgeService):
    """Collect evidence once, then score each rubric question independently."""

    async def score_one(self, *, task: Any, question: dict[str, Any], evidence: EvidenceCollection):
        from .models import QuestionJudgment
        agent = Agent(
            self.model,
            output_type=QuestionJudgment,
            system_prompt=(
                "You are a rubric-specific scoring judge. Score only the one supplied "
                "rubric question using only the frozen evidence packet. Do not search, "
                "add evidence, or let other rubric questions affect this decision. "
                "Apply the question's own anchors and cite the supplied evidence ids."
            ),
        )
        prompt = json.dumps({
            "task": task,
            "rubric_question": question,
            "frozen_evidence_packet": evidence.model_dump(),
        }, ensure_ascii=False)
        return await agent.run(prompt)

    async def evaluate_per_question(self, *, task: Any, questions: list[dict[str, Any]], agent_output: str):
        evidence = await self.collect(task=task, questions=questions, agent_output=agent_output)
        results = await __import__('asyncio').gather(*(
            self.score_one(task=task, question=q, evidence=evidence) for q in questions
        ))
        return evidence, [result.output for result in results]
