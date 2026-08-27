"""Scoring-only Judge for frozen evidence/claim ablations.

This service intentionally has no evidence tools. It isolates rubric score-anchor
representation after facts and claims have already been frozen by human review.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext


class FrozenScoringDecision(BaseModel):
    question_id: str
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    selected_anchor_label: str
    rationale: str
    fact_ids_used: list[str] = Field(default_factory=list)
    fact_ids_not_used: list[str] = Field(default_factory=list)


@dataclass
class FrozenScoringDeps:
    question: dict[str, Any]
    valid_fact_ids: frozenset[str]


def build_frozen_scoring_agent(model: Any) -> Any:
    agent = Agent(
        model,
        deps_type=FrozenScoringDeps,
        output_type=FrozenScoringDecision,
        system_prompt=(
            "You are a scoring-only rubric judge. The supplied frozen facts, factual claims, "
            "missing facts, contradictions, evidence classes, and source applicability decisions "
            "are authoritative. Do not investigate, request tools, add facts, delete facts, dispute "
            "facts, reinterpret whether a source was agent-visible, or invent evidence. Your only "
            "task is to select exactly one declared score anchor whose description best matches the "
            "frozen factual state. Use only supplied fact_id values in fact_ids_used/not_used. "
            "Do not infer a continuous score between anchors."
        ),
    )

    @agent.output_validator
    async def validate(ctx: RunContext[FrozenScoringDeps], output: FrozenScoringDecision) -> FrozenScoringDecision:
        anchors = [a for a in (ctx.deps.question.get("score_anchors") or []) if isinstance(a, dict)]
        matching = [a for a in anchors if abs(float(a["score"]) - output.score) <= 1e-9]
        if not matching:
            raise ModelRetry(
                f"Select exactly one declared score anchor {[float(a['score']) for a in anchors]}; "
                f"received {output.score}."
            )
        expected_label = str(matching[0].get("label") or "")
        if output.selected_anchor_label != expected_label:
            raise ModelRetry(
                f"selected_anchor_label must be {expected_label!r} for score {output.score}; "
                f"received {output.selected_anchor_label!r}."
            )
        referenced = set(output.fact_ids_used) | set(output.fact_ids_not_used)
        unknown = referenced - ctx.deps.valid_fact_ids
        if unknown:
            raise ModelRetry(f"Unknown fact_id values: {sorted(unknown)}")
        return output

    return agent


class FrozenEvidenceScoringService:
    def __init__(self, model: Any):
        self.model = model
        self.last_usage: dict[str, Any] | None = None
        self.last_provenance: dict[str, Any] = {}

    async def evaluate(self, *, question: dict[str, Any], bundle: dict[str, Any]) -> FrozenScoringDecision:
        facts = [x for x in (bundle.get("facts") or []) if isinstance(x, dict)]
        fact_ids = frozenset(str(x["fact_id"]) for x in facts)
        agent = build_frozen_scoring_agent(self.model)
        prompt = json.dumps({
            "question": question,
            "frozen_evidence_bundle": {
                "schema_version": bundle.get("schema_version"),
                "case_id": bundle.get("case_id"),
                "question_id": bundle.get("question_id"),
                "facts": facts,
                "claim_set": bundle.get("claim_set") or [],
                "missing_facts": bundle.get("missing_facts") or [],
                "contradictions": bundle.get("contradictions") or [],
            },
            "instruction": (
                "Treat the frozen bundle as complete and authoritative for this experiment. "
                "Map it to one declared anchor without searching or changing the factual state."
            ),
        }, ensure_ascii=False)
        result = await agent.run(prompt, deps=FrozenScoringDeps(question=question, valid_fact_ids=fact_ids))
        usage = getattr(result, "usage", None)
        self.last_usage = dataclasses.asdict(usage) if usage is not None and dataclasses.is_dataclass(usage) else None
        if self.last_usage and self.last_usage.get("cost") is not None:
            self.last_usage["cost"] = str(self.last_usage["cost"])
        selected = next(
            a for a in question.get("score_anchors") or []
            if abs(float(a["score"]) - result.output.score) <= 1e-9
        )
        self.last_provenance = {
            "mode": "frozen_evidence_scoring_only",
            "tools_available": [],
            "fact_ids": sorted(fact_ids),
            "declared_score_anchors": question.get("score_anchors") or [],
            "selected_anchor": selected,
        }
        return result.output
