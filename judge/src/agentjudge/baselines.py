"""Meta-evaluation baseline Judges.

These services are not production evidence policies. They exist only to compare
Full-Trace, Static Retrieval and the autonomous Agentic Evidence Judge under a
shared structured-output contract.
"""
from __future__ import annotations

import json
import dataclasses
from typing import Any, Iterable

from .agents import declared_anchor_scores
from .models import EvidenceQuery, EvidenceRecord, JudgeRequest, QuestionJudgment

try:
    from pydantic_ai import Agent, ModelRetry
except ImportError as exc:  # pragma: no cover
    Agent = None  # type: ignore[assignment]
    ModelRetry = RuntimeError  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


BASELINE_SYSTEM_PROMPT = (
    "You are a rubric-question judge in a controlled meta-evaluation baseline. "
    "Judge only from the evidence records included in the prompt. Do not claim "
    "that an event or relation exists unless the supplied records establish it. "
    "Cite evidence_id values, distinguish direct runtime events from indirect or "
    "retrospective evidence, and report missing evidence explicitly."
)


class FullTraceJudgeService:
    """No-tools baseline that places the complete frozen snapshot in the prompt."""

    mode = "full_trace"

    def __init__(self, model: Any):
        _require_pydantic_ai()
        self.model = model
        self.last_provenance: dict[str, Any] = {}
        self.last_usage: dict[str, Any] | None = None

    async def evaluate(self, request: JudgeRequest, records: Iterable[EvidenceRecord]) -> QuestionJudgment:
        snapshot = list(records)
        agent = _baseline_agent(self.model, request.rubric_question or {})
        prompt = _prompt(request, snapshot, mode=self.mode)
        result = await agent.run(prompt)
        self.last_usage = _usage(result)
        self.last_provenance = {
            "judge_mode": self.mode,
            "record_count": len(snapshot),
            "evidence_ids": [record.evidence_id for record in snapshot],
            "prompt_chars": len(prompt),
            "retrieval_actions": [],
            "scoring": _scoring_provenance(request.rubric_question or {}, result.output.score),
        }
        return result.output


class StaticRetrievalJudgeService:
    """No-tools baseline using a deterministic generic lexical top-k snapshot."""

    mode = "static_retrieval"

    def __init__(self, model: Any, *, top_k: int = 20):
        _require_pydantic_ai()
        if not 1 <= top_k <= 30:
            raise ValueError("top_k must be in [1, 30]")
        self.model = model
        self.top_k = top_k
        self.last_provenance: dict[str, Any] = {}
        self.last_usage: dict[str, Any] | None = None

    async def evaluate(self, request: JudgeRequest, evidence: Any) -> QuestionJudgment:
        question = request.rubric_question or {}
        query_text = " ".join(str(question.get(key) or "") for key in ("question", "evidence", "anchors"))
        selected = evidence.search(EvidenceQuery(text=query_text, limit=self.top_k))
        agent = _baseline_agent(self.model, request.rubric_question or {})
        prompt = _prompt(request, selected, mode=self.mode)
        result = await agent.run(prompt)
        self.last_usage = _usage(result)
        self.last_provenance = {
            "judge_mode": self.mode,
            "record_count": len(selected),
            "evidence_ids": [record.evidence_id for record in selected],
            "prompt_chars": len(prompt),
            "retrieval_actions": [{
                "operation": "static_search",
                "query": query_text,
                "top_k": self.top_k,
                "result_ids": [record.evidence_id for record in selected],
            }],
            "scoring": _scoring_provenance(request.rubric_question or {}, result.output.score),
        }
        return result.output


def _scoring_provenance(question: dict[str, Any], score: float) -> dict[str, Any]:
    anchors = [
        dict(anchor) for anchor in (question.get("score_anchors") or [])
        if isinstance(anchor, dict) and anchor.get("score") is not None
    ]
    selected = next(
        (anchor for anchor in anchors if abs(float(anchor["score"]) - score) <= 1e-9),
        None,
    )
    return {
        "scoring_mode": "discrete_anchor" if anchors else "continuous_legacy",
        "declared_score_anchors": anchors,
        "selected_anchor": selected,
        "selected_score": score,
    }


def _baseline_agent(model: Any, question: dict[str, Any]) -> Any:
    agent = Agent(model, output_type=QuestionJudgment, system_prompt=BASELINE_SYSTEM_PROMPT)
    scores = declared_anchor_scores(question)
    if scores:
        @agent.output_validator
        async def validate_discrete_anchor(output: QuestionJudgment) -> QuestionJudgment:
            if not any(abs(output.score - score) <= 1e-9 for score in scores):
                raise ModelRetry(
                    f"The final score must select exactly one declared score anchor {scores}; "
                    f"received {output.score}."
                )
            return output
    return agent


def _prompt(request: JudgeRequest, records: list[EvidenceRecord], *, mode: str) -> str:
    return json.dumps({
        "mode": mode,
        "task": request.case.get("task") if isinstance(request.case, dict) else request.case,
        "rubric_question": request.rubric_question,
        "agent_output": request.agent_output,
        "deterministic_result": request.deterministic_result,
        "evidence_records": [record.model_dump() for record in records],
    }, ensure_ascii=False, default=str)



def _usage(result: Any) -> dict[str, Any] | None:
    usage = getattr(result, "usage", None)
    if usage is None or not dataclasses.is_dataclass(usage):
        return None
    value = dataclasses.asdict(usage)
    if value.get("cost") is not None:
        value["cost"] = str(value["cost"])
    return value

def _require_pydantic_ai() -> None:
    if Agent is None:
        raise RuntimeError("baseline Judges require pydantic-ai") from _IMPORT_ERROR
