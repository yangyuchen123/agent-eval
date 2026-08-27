"""Retrieval-only autonomous investigator used by rubric-representation ablations.

This is an experimental observation mode, not a replacement for QuestionJudge.
It exposes the same generic runtime navigation primitives but deliberately has no
score, status, or anchor-selection output.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from .evidence import EvidenceProvider
from .models import EvidenceQuery


class InvestigationFinding(BaseModel):
    finding_id: str
    statement: str
    basis: Literal["observed", "derived", "inferred", "missing"]
    evidence_refs: list[str] = Field(default_factory=list)


class RetrievalInvestigation(BaseModel):
    question_id: str
    factual_summary: str
    findings: list[InvestigationFinding] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    stop_reason: str


@dataclass
class RetrievalInvestigationDeps:
    question: dict[str, Any]
    evidence: EvidenceProvider
    tool_trajectory: list[dict[str, Any]] = field(default_factory=list)


def build_retrieval_investigator(model: Any) -> Any:
    agent = Agent(
        model,
        deps_type=RetrievalInvestigationDeps,
        output_type=RetrievalInvestigation,
        system_prompt=(
            "You are an autonomous evidence investigator. Decide what evidence is needed "
            "for the supplied rubric question. Use the generic runtime search and navigation "
            "tools to investigate, follow useful context, and look for supporting and "
            "contradicting evidence. Do not assume a fixed query plan. Cite evidence_id values. "
            "Preserve the distinction between direct runtime events, derived relations, artifact "
            "observations, and retrospective artifacts. If your investigation did not find "
            "evidence, say so explicitly rather than inventing it. This experiment ends after "
            "factual investigation: do not choose a score, score anchor, confidence, or judgment status."
        ),
    )

    @agent.tool
    async def search_evidence(
        ctx: RunContext[RetrievalInvestigationDeps],
        query: str | None = None,
        source: str | None = None,
        event_type: list[str] | None = None,
        tool_name: str | None = None,
        agent_id: str | None = None,
        parent_agent_id: str | None = None,
        target_agent_id: str | None = None,
        tool_call_id: str | None = None,
        message_id: str | None = None,
        before: str | None = None,
        after: str | None = None,
        limit: Annotated[int, Field(ge=1, le=30)] = 12,
    ) -> list[dict[str, Any]]:
        params = {
            "query": query, "source": source, "event_type": event_type or [],
            "tool_name": tool_name, "agent_id": agent_id,
            "parent_agent_id": parent_agent_id, "target_agent_id": target_agent_id,
            "tool_call_id": tool_call_id, "message_id": message_id,
            "before": before, "after": after, "limit": limit,
        }
        records = ctx.deps.evidence.search(EvidenceQuery(
            text=query, source=source, event_type=event_type or [], tool_name=tool_name,
            agent_id=agent_id, parent_agent_id=parent_agent_id, target_agent_id=target_agent_id,
            tool_call_id=tool_call_id, message_id=message_id, before=before, after=after,
            limit=limit,
        ))
        ctx.deps.tool_trajectory.append({
            "operation": "search", "parameters": params,
            "result_ids": [record.evidence_id for record in records],
        })
        return [record.model_dump() for record in records]

    @agent.tool
    async def get_evidence(ctx: RunContext[RetrievalInvestigationDeps], evidence_id: str) -> dict[str, Any]:
        record = ctx.deps.evidence.get(evidence_id)
        ctx.deps.tool_trajectory.append({
            "operation": "get", "parameters": {"evidence_id": evidence_id},
            "result_ids": [record.evidence_id] if record else [],
        })
        return record.model_dump() if record else {"error": "evidence_not_found", "evidence_id": evidence_id}

    @agent.tool
    async def get_call_context(ctx: RunContext[RetrievalInvestigationDeps], tool_call_id: str) -> list[dict[str, Any]]:
        records = ctx.deps.evidence.call_context(tool_call_id)
        ctx.deps.tool_trajectory.append({
            "operation": "call_context", "parameters": {"tool_call_id": tool_call_id},
            "result_ids": [record.evidence_id for record in records],
        })
        return [record.model_dump() for record in records]

    @agent.tool
    async def get_related_evidence(
        ctx: RunContext[RetrievalInvestigationDeps], evidence_id: str, relation: str = "related"
    ) -> list[dict[str, Any]]:
        records = ctx.deps.evidence.related(evidence_id, relation)
        ctx.deps.tool_trajectory.append({
            "operation": "related",
            "parameters": {"evidence_id": evidence_id, "relation": relation},
            "result_ids": [record.evidence_id for record in records],
        })
        return [record.model_dump() for record in records]

    return agent


class RetrievalInvestigationService:
    def __init__(self, model: Any, evidence: EvidenceProvider):
        self.model = model
        self.evidence = evidence
        self.last_tool_trajectory: list[dict[str, Any]] = []
        self.last_provider_trajectory: list[dict[str, Any]] = []
        self.last_usage: dict[str, Any] | None = None
        self.last_message_history: list[dict[str, Any]] = []

    async def investigate(
        self, *, task: str, question: dict[str, Any], trace_ref: Any = None,
        agent_output: str = "",
    ) -> RetrievalInvestigation:
        deps = RetrievalInvestigationDeps(question=question, evidence=self.evidence)
        prompt = json.dumps({
            "task": task,
            "question": question,
            "agent_output": agent_output,
            "trace_ref": trace_ref,
            "instruction": (
                "Investigate autonomously with the generic evidence tools. Return only a factual "
                "investigation record. Do not select or recommend any score anchor, score, confidence, "
                "or final supported/partially-supported judgment."
            ),
        }, ensure_ascii=False)
        result = await build_retrieval_investigator(self.model).run(prompt, deps=deps)
        self.last_tool_trajectory = list(deps.tool_trajectory)
        self.last_message_history = json.loads(result.all_messages_json())
        provider_trajectory = getattr(self.evidence, "query_trajectory", None)
        self.last_provider_trajectory = list(provider_trajectory()) if callable(provider_trajectory) else []
        usage = getattr(result, "usage", None)
        self.last_usage = dataclasses.asdict(usage) if usage is not None and dataclasses.is_dataclass(usage) else None
        if self.last_usage and self.last_usage.get("cost") is not None:
            self.last_usage["cost"] = str(self.last_usage["cost"])
        return result.output
