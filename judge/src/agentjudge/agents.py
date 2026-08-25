"""PydanticAI agent factories for autonomous question judgments."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .evidence import EvidenceProvider
from .models import EvidenceQuery, QuestionJudgment

try:
    from pydantic_ai import Agent, RunContext
except ImportError as exc:  # pragma: no cover - dependency is installed by judge project
    Agent = None  # type: ignore[assignment,misc]
    RunContext = Any  # type: ignore[assignment,misc]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


@dataclass
class QuestionJudgeDeps:
    question: dict[str, Any]
    evidence: EvidenceProvider


def _require_pydantic_ai() -> None:
    if Agent is None:
        raise RuntimeError(
            "agent-judge requires pydantic-ai; install judge[dev] or judge dependencies"
        ) from _IMPORT_ERROR


def build_question_agent(model: Any) -> Any:
    """Build an autonomous question agent with generic read-only tools.

    Tool names describe navigation primitives only. They intentionally do not
    encode rubric concepts such as handoff, assignment, or consumption.
    """
    _require_pydantic_ai()
    agent = Agent(
        model,
        deps_type=QuestionJudgeDeps,
        output_type=QuestionJudgment,
        system_prompt=(
            "You are an autonomous evidence investigator and rubric-question judge. "
            "Decide what evidence is needed for the supplied question. Use the generic "
            "runtime search and navigation tools to investigate, follow useful context, "
            "and look for supporting and contradicting evidence. Do not assume a fixed "
            "query plan. Cite evidence_id values. Preserve the distinction between "
            "direct runtime events, derived relations, artifact observations, and "
            "retrospective artifacts. If your investigation did not find evidence, "
            "say so explicitly rather than inventing it."
        ),
    )

    @agent.tool
    async def search_evidence(
        ctx: RunContext[QuestionJudgeDeps],
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
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        records = ctx.deps.evidence.search(EvidenceQuery(
            text=query, source=source, event_type=event_type or [], tool_name=tool_name,
            agent_id=agent_id, parent_agent_id=parent_agent_id, target_agent_id=target_agent_id,
            tool_call_id=tool_call_id, message_id=message_id, before=before, after=after,
            limit=limit,
        ))
        return [record.model_dump() for record in records]

    @agent.tool
    async def get_evidence(ctx: RunContext[QuestionJudgeDeps], evidence_id: str) -> dict[str, Any]:
        record = ctx.deps.evidence.get(evidence_id)
        return record.model_dump() if record else {"error": "evidence_not_found", "evidence_id": evidence_id}

    @agent.tool
    async def get_call_context(ctx: RunContext[QuestionJudgeDeps], tool_call_id: str) -> list[dict[str, Any]]:
        return [record.model_dump() for record in ctx.deps.evidence.call_context(tool_call_id)]

    @agent.tool
    async def get_related_evidence(
        ctx: RunContext[QuestionJudgeDeps], evidence_id: str, relation: str = "related"
    ) -> list[dict[str, Any]]:
        """Navigate generic relations such as parent, child, same_agent, before, after."""
        return [record.model_dump() for record in ctx.deps.evidence.related(evidence_id, relation)]

    return agent
