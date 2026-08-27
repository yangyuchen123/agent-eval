"""Small AgentEval-side contract for an independent Agent Judge.

This module deliberately contains no evidence retrieval, runtime parsing, LLM
prompt, or judge tool loop.  It only adapts a case/skill invocation to a
JudgeClient and converts the response into AgentEval's SkillResult.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import urllib.error
import urllib.request
from typing import Any, Mapping, Protocol

from .protocols import Case, SkillResult
from .rubrics import Rubric
from .skills.base import Skill


@dataclass(frozen=True)
class JudgeRequest:
    case: Case
    rubric: Any
    agent_output: str
    rubric_question: dict[str, Any] = field(default_factory=dict)
    trace_ref: Any = None
    artifact_ref: Any = None
    deterministic_result: Mapping[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        rubric = self.rubric.to_dict() if hasattr(self.rubric, "to_dict") else self.rubric
        return {
            "schema_version": "agenteval.judge_request.v1",
            "case": self.case.to_dict(),
            "rubric": rubric,
            "rubric_question": self.rubric_question,
            "agent_output": self.agent_output,
            "trace_ref": self.trace_ref,
            "artifact_ref": self.artifact_ref,
            "deterministic_result": dict(self.deterministic_result) if self.deterministic_result else None,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class JudgeResponse:
    score: float | None
    subscores: dict[str, float | None] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    confidence: float | None = None
    evidence_refs: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    status: str = "scored"
    question_judgments: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JudgeResponse":
        return cls(
            score=_number_or_none(value.get("score"), "score"),
            subscores={str(k): _number_or_none(v, f"subscores[{k}]") for k, v in dict(value.get("subscores") or {}).items()},
            reasons={str(k): str(v) for k, v in dict(value.get("reasons") or {}).items()},
            confidence=_number_or_none(value.get("confidence"), "confidence"),
            evidence_refs=[str(v) for v in (value.get("evidence_refs") or [])],
            findings=[dict(v) for v in (value.get("findings") or []) if isinstance(v, Mapping)],
            provenance=dict(value.get("provenance") or {}),
            status=str(value.get("status") or "scored"),
            question_judgments=[dict(v) for v in (value.get("question_judgments") or []) if isinstance(v, Mapping)],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "agenteval.judge_response.v1",
            "score": self.score,
            "subscores": self.subscores,
            "reasons": self.reasons,
            "confidence": self.confidence,
            "evidence_refs": self.evidence_refs,
            "findings": self.findings,
            "provenance": self.provenance,
            "status": self.status,
            "question_judgments": self.question_judgments,
        }


class JudgeClient(Protocol):
    """Client for a local plugin or remote independent Agent Judge."""

    def evaluate(self, request: JudgeRequest) -> JudgeResponse | Mapping[str, Any]:
        ...


class JudgeClientError(RuntimeError):
    """The independent Judge endpoint rejected or could not answer a request."""


class HttpJudgeClient:
    """Minimal HTTP transport for the versioned independent Judge contract.

    This class is intentionally only a transport adapter: it does not know how
    evidence is indexed, queried, or judged. The default path is a proposal for
    the standalone Judge service and can be overridden by ``endpoint``.
    """

    def __init__(
        self,
        base_url: str,
        *,
        endpoint: str = "/v1/judge/evaluate",
        api_key: str | None = None,
        timeout: float = 90.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint = endpoint if endpoint.startswith("/") else "/" + endpoint
        self.api_key = api_key
        self.timeout = timeout
        if not self.base_url:
            raise ValueError("base_url is required")

    def evaluate(self, request: JudgeRequest) -> JudgeResponse:
        url = self.base_url + self.endpoint
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = json.dumps(request.to_dict(), ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:  # noqa: S310
                status = int(response.status)
                raw = response.read().decode("utf-8")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                detail = exc.read().decode("utf-8", errors="replace")[:2000]
                raise JudgeClientError(f"Judge HTTP {exc.code}: {detail}") from exc
            raise JudgeClientError(f"Judge request failed: {exc}") from exc
        if status >= 400:
            raise JudgeClientError(f"Judge HTTP {status}: {raw[:2000]}")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise JudgeClientError("Judge response is not JSON") from exc
        if isinstance(value, Mapping) and isinstance(value.get("result"), Mapping):
            value = value["result"]
        if not isinstance(value, Mapping):
            raise JudgeClientError("Judge response must be an object")
        result = JudgeResponse.from_dict(value)
        # Keep transport provenance separate from evidence provenance.
        return JudgeResponse(
            score=result.score, subscores=result.subscores, reasons=result.reasons,
            confidence=result.confidence, evidence_refs=result.evidence_refs,
            findings=result.findings,
            provenance={**result.provenance, "transport": {"url": url, "status": status}},
            status=result.status,
        )


class JudgeClientSkill(Skill):
    """Thin AgentEval skill wrapper around an independent JudgeClient."""

    skill_id = "judge_client"
    role = "diagnostic"
    question = "Can the configured independent Judge evaluate this case?"
    definition_version = "agenteval.judge-client-skill.v1"

    def __init__(
        self,
        client: JudgeClient,
        rubric: Rubric | Mapping[str, Any] | str,
        *,
        skill_id: str | None = None,
        role: str = "diagnostic",
    ) -> None:
        self.client = client
        self.rubric = rubric
        if skill_id:
            self.skill_id = skill_id
        self.role = role

    def evaluate(self, case: Case, output: str) -> SkillResult:
        deterministic = case.context.get("deterministic_result")
        request = JudgeRequest(
            case=_public_case(case),
            rubric=self.rubric,
            rubric_question=dict(case.context.get("rubric_question") or {}),
            agent_output=output,
            trace_ref=case.context.get("trace_ref") or case.context.get("attempt_ref"),
            artifact_ref=case.context.get("artifact_ref"),
            deterministic_result=deterministic if isinstance(deterministic, Mapping) else None,
            metadata={
                "env_name": case.metadata.get("env_name"),
                "task_id": case.metadata.get("task_id") or case.case_id,
            },
        )
        raw = self.client.evaluate(request)
        response = raw if isinstance(raw, JudgeResponse) else JudgeResponse.from_dict(raw)
        if response.score is not None:
            _validate_number(response.score, "score")
        for key, value in response.subscores.items():
            if value is not None:
                _validate_number(value, f"subscores[{key}]")
        if response.confidence is not None:
            _validate_number(response.confidence, "confidence")
        return SkillResult(
            skill_id=self.skill_id,
            status=response.status,
            score=response.score,
            subscores=response.subscores,
            reasons=response.reasons,
            evidence={
                "judge_response": response.to_dict(),
                "evidence_refs": response.evidence_refs,
                "findings": response.findings,
            },
            diagnostics={"confidence": response.confidence, "judge_provenance": response.provenance},
        )



class MultiQuestionJudgeSkill(Skill):
    """Run one independent Judge request per rubric question and aggregate.

    The independent Judge remains single-question and autonomous. This class
    owns only orchestration and weighted aggregation at the AgentEval layer.
    """

    skill_id = "multi_question_judge"
    role = "diagnostic"
    question = "Can independent question judges evaluate the rubric dimensions?"
    definition_version = "agenteval.multi-question-judge.v1"

    def __init__(self, client: JudgeClient, rubric: Rubric | Mapping[str, Any] | str,
                 *, skill_id: str | None = None, role: str = "diagnostic") -> None:
        self.client = client
        self.rubric = rubric
        if skill_id:
            self.skill_id = skill_id
        self.role = role

    def evaluate(self, case: Case, output: str) -> SkillResult:
        questions = _rubric_questions(self.rubric)
        if not questions:
            questions = [{"id": "overall", "question": "Judge the case against the supplied rubric."}]
        judgments: list[dict[str, Any]] = []
        weighted: list[tuple[float, float]] = []
        all_refs: list[str] = []
        provenance: list[dict[str, Any]] = []
        statuses: list[str] = []
        for question in questions:
            request = JudgeRequest(
                case=_public_case(case),
                rubric=self.rubric,
                rubric_question=dict(question),
                agent_output=output,
                trace_ref=case.context.get("trace_ref") or case.context.get("attempt_ref"),
                artifact_ref=case.context.get("artifact_ref"),
                deterministic_result=_deterministic_result(case),
                metadata={
                    "env_name": case.metadata.get("env_name"),
                    "task_id": case.metadata.get("task_id") or case.case_id,
                    "orchestration": "multi_question",
                    "question_id": question.get("id"),
                },
            )
            raw = self.client.evaluate(request)
            response = raw if isinstance(raw, JudgeResponse) else JudgeResponse.from_dict(raw)
            if response.score is not None:
                _validate_number(response.score, f"question[{question.get('id')}].score")
                anchor_scores = _question_anchor_scores(question)
                if anchor_scores and not any(abs(response.score - value) <= 1e-9 for value in anchor_scores):
                    raise ValueError(
                        f"question[{question.get('id')}].score must select one of "
                        f"the declared anchors {anchor_scores}, got {response.score}")
                weight = float(question.get("weight", 1.0))
                if weight > 0:
                    weighted.append((response.score, weight))
            all_refs.extend(response.evidence_refs)
            judgments.append({"question": dict(question), "response": response.to_dict()})
            provenance.append(response.provenance)
            statuses.append(response.status)
        score = None
        if weighted:
            score = round(sum(value * weight for value, weight in weighted) / sum(weight for _, weight in weighted), 6)
        if any(status in {"error", "judge_error"} for status in statuses):
            status = "error"
        elif any(status == "incomplete_evidence" for status in statuses):
            status = "incomplete_evidence"
        else:
            status = "ok"
        rubric_data = self.rubric.to_dict() if isinstance(self.rubric, Rubric) else (dict(self.rubric) if isinstance(self.rubric, Mapping) else {})
        judge_models = [str(item.get("model")) for item in provenance if item.get("model")]
        return SkillResult(
            skill_id=self.skill_id, status=status, score=score,
            subscores={str(j["question"].get("id")): j["response"].get("score") for j in judgments},
            reasons={str(j["question"].get("id")): _question_reason(j["response"]) for j in judgments},
            evidence={"question_judgments": judgments, "evidence_refs": list(dict.fromkeys(all_refs)),
                      "rubric": rubric_data},
            diagnostics={
                "judge_provenance": provenance, "question_count": len(questions),
                "question_statuses": statuses,
                "judge": {
                    "model": judge_models[0] if judge_models else None,
                    "rubric_id": rubric_data.get("rubric_id"),
                    "rubric_version": rubric_data.get("version"),
                    "evaluator_version": self.definition_version,
                },
            },
        )


def _public_case(case: Case) -> Case:
    """Remove evaluator-private runtime payloads before crossing Judge boundary."""
    return Case(
        case_id=case.case_id, task=case.task, expected=dict(case.expected),
        context={}, metadata=dict(case.metadata),
    )


def _rubric_questions(rubric: Rubric | Mapping[str, Any] | str) -> list[dict[str, Any]]:
    if isinstance(rubric, Rubric):
        allowed = list(rubric.allowed_scores)
        return [{**q.to_dict(), "allowed_scores": allowed} for q in rubric.questions]
    if isinstance(rubric, Mapping):
        allowed = [float(x) for x in (rubric.get("allowed_scores") or [])]
        return [
            {**dict(q), **({"allowed_scores": allowed} if allowed else {})}
            for q in (rubric.get("questions") or []) if isinstance(q, Mapping)
        ]
    if isinstance(rubric, str):
        try:
            value = json.loads(rubric)
        except json.JSONDecodeError:
            return []
        return _rubric_questions(value) if isinstance(value, Mapping) else []
    return []


def _question_anchor_scores(question: Mapping[str, Any]) -> list[float]:
    values: list[float] = []
    for anchor in question.get("score_anchors") or []:
        if isinstance(anchor, Mapping) and anchor.get("score") is not None:
            values.append(float(anchor["score"]))
    return values


def _deterministic_result(case: Case) -> Mapping[str, Any] | None:
    value = case.context.get("deterministic_result")
    return value if isinstance(value, Mapping) else None


def _question_reason(response: Mapping[str, Any]) -> str:
    reasons = response.get("reasons") or {}
    if reasons:
        return "; ".join(f"{key}: {value}" for key, value in reasons.items())
    findings = response.get("findings") or []
    return "; ".join(str(item.get("statement", "")) for item in findings if isinstance(item, Mapping))

def _validate_number(value: float, name: str) -> float:
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be in [0,1], got {value}")
    return value


def _number_or_none(value: Any, name: str) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric or null") from exc
    _validate_number(result, name)
    return result
