"""HTTP boundary for the independent, single-question Agent Judge.

The service is deliberately a transport adapter around ``QuestionJudgeService``.
It creates an evidence environment for the request's trace reference, runs one
question, and returns the judgment plus diagnostic provenance. Rubric planning
and multi-question aggregation remain in AgentEval.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from .catalog import EvidenceCatalog
from .models import JudgeRequest, QuestionJudgment, JointQuestionJudgment
from .service import JointQuestionJudgeService, QuestionJudgeService


class JudgeHttpApplication:
    """Small ASGI application with no mandatory FastAPI dependency."""

    def __init__(
        self,
        model: Any,
        *,
        evidence_factory: Callable[[JudgeRequest], EvidenceCatalog] | None = None,
    ) -> None:
        self.model = model
        self.evidence_factory = evidence_factory or default_evidence_factory

    async def evaluate(self, request: JudgeRequest) -> dict[str, Any]:
        evidence = self.evidence_factory(request)
        protocol = os.environ.get("JUDGE_PROTOCOL", "B").strip().upper()
        questions = _rubric_questions(request)

        # Production defaults to B: one task-level call with the complete rubric
        # and trajectory.  A single-question request remains compatible with the
        # legacy service, even when the process default is B.
        if protocol == "B" and len(questions) > 1:
            service = JointQuestionJudgeService(self.model, evidence)
            judgment = await service.evaluate(request)
            return _joint_response(self.model, request, judgment, evidence, service)

        service = QuestionJudgeService(self.model, evidence)
        judgment = await service.evaluate(request)
        integrity = validate_judgment(judgment, evidence)
        provenance = {
            "model": _model_name(self.model),
            "protocol": "single_question",
            "protocol_version": "agent-eval.abcd.frozen.v1/single-question",
            "trace_ref": request.trace_ref,
            "evidence_manifest": evidence.manifest() if hasattr(evidence, "manifest") else {"record_count": len(getattr(evidence, "records", []))},
            "query_trajectory": service.last_query_trajectory,
            "token_usage": service.last_usage,
            "scoring": service.last_scoring_provenance,
            "integrity": integrity,
        }
        status = "incomplete_evidence" if integrity["issues"] else "scored"
        return {
            "schema_version": "agentjudge.question_judgment.v1",
            "score": judgment.score,
            "subscores": {judgment.question_id: judgment.score},
            "reasons": {
                claim.claim_id: claim.statement for claim in judgment.claims
            },
            "confidence": judgment.confidence,
            "evidence_refs": judgment.evidence_refs,
            "findings": [claim.model_dump() for claim in judgment.claims],
            "provenance": provenance,
            "status": status,
            "question_judgment": judgment.model_dump(),
        }


def _rubric_questions(request: JudgeRequest) -> list[dict[str, Any]]:
    rubric = request.rubric
    if isinstance(rubric, dict):
        questions = rubric.get("questions") or rubric.get("rubric_questions") or []
        return [dict(q) for q in questions if isinstance(q, dict)]
    return [dict(request.rubric_question)] if request.rubric_question else []


def _joint_response(model: Any, request: JudgeRequest, judgment: JointQuestionJudgment, evidence: EvidenceCatalog, service: JointQuestionJudgeService | None = None) -> dict[str, Any]:
    question_judgments = [item.model_dump() for item in judgment.question_judgments]
    refs = list(dict.fromkeys(ref for item in judgment.question_judgments for ref in item.evidence_refs))
    integrity_issues: list[str] = []
    for item in judgment.question_judgments:
        integrity_issues.extend(validate_judgment(item, evidence)["issues"])
    integrity = {
        "issues": list(dict.fromkeys(integrity_issues)),
        "known_evidence_count": len(getattr(evidence, "records", [])),
    }
    status = "incomplete_evidence" if integrity["issues"] else judgment.status
    return {
        "schema_version": "agentjudge.joint_judgment.v1",
        "score": judgment.overall_score,
        "subscores": {item.question_id: item.score for item in judgment.question_judgments},
        "reasons": {
            claim.claim_id: claim.statement
            for item in judgment.question_judgments
            for claim in item.claims
        },
        "confidence": judgment.confidence,
        "evidence_refs": refs,
        "findings": [claim.model_dump() for item in judgment.question_judgments for claim in item.claims],
        "question_judgments": question_judgments,
        "provenance": {
            "model": _model_name(model),
            "protocol": "B_joint_multi_rubric",
            "protocol_version": "agent-eval.abcd.frozen.v1/B",
            "one_shot": not bool((request.metadata or {}).get("enable_joint_tools")),
            "trace_ref": request.trace_ref,
            "question_count": len(question_judgments),
            "evidence_manifest": evidence.manifest() if hasattr(evidence, "manifest") else {"record_count": len(getattr(evidence, "records", []))},
            "query_trajectory": service.last_query_trajectory if service else [],
            "token_usage": service.last_usage if service else None,
            "scoring": service.last_scoring_provenance if service else {"scoring_mode": "joint_multi_rubric"},
            "integrity": integrity,
        },
        "status": status,
    }


def default_evidence_factory(request: JudgeRequest) -> EvidenceCatalog:
    """Resolve only an explicit local attempt directory from ``trace_ref``.

    Remote trace retrieval is intentionally outside this service. Callers that
    use another runtime can inject ``evidence_factory`` without changing the
    Judge contract.
    """
    # Artifact-only rubric questions intentionally omit trace_ref.  Harbor's
    # artifact_ref carries the same trial_dir and must still build the catalog;
    # otherwise supported artifact claims cannot cite resolvable evidence and
    # the whole case is incorrectly marked incomplete_evidence.
    ref = request.trace_ref or request.artifact_ref
    if isinstance(ref, dict):
        scheme = str(ref.get("scheme") or "")
        if scheme == "harbor":
            trial_dir = ref.get("trial_dir") or ref.get("path")
            if not trial_dir:
                raise ValueError("Harbor trace_ref requires trial_dir")
            path = Path(str(trial_dir)).expanduser().resolve()
            _require_allowed_path(path)
            if not path.is_dir():
                raise ValueError(f"Harbor trial directory does not exist: {trial_dir}")
            return EvidenceCatalog.from_harbor_trial(path)
        ref = ref.get("attempt_dir") or ref.get("path") or ref.get("trace_path")
    if not ref:
        return EvidenceCatalog()
    path = Path(str(ref)).expanduser().resolve()
    if path.is_file():
        path = path.parent
    _require_allowed_path(path)
    if not path.is_dir():
        raise ValueError(f"trace_ref is not an attempt directory: {ref}")
    return EvidenceCatalog.from_attempt_dir(path)


def _require_allowed_path(path: Path) -> None:
    """Reject local evidence outside explicitly configured roots."""
    raw = os.environ.get("JUDGE_ALLOWED_ROOTS", "").strip()
    if not raw:
        raise ValueError("JUDGE_ALLOWED_ROOTS must explicitly allow local evidence paths")
    roots = [Path(value).expanduser().resolve() for value in raw.split(os.pathsep) if value.strip()]
    if not any(path == root or root in path.parents for root in roots):
        raise ValueError(f"local evidence path is outside JUDGE_ALLOWED_ROOTS: {path}")


def validate_judgment(judgment: QuestionJudgment, evidence: EvidenceCatalog) -> dict[str, Any]:
    """Apply only schema-level integrity checks, never rubric claim policy."""
    known = {record.evidence_id for record in evidence.records}
    refs = set(judgment.evidence_refs)
    issues: list[str] = []
    missing = sorted(ref for ref in refs if ref not in known)
    if missing:
        issues.append(f"unresolvable evidence_refs: {missing}")
    for claim in judgment.claims:
        if claim.status == "supported" and not claim.evidence_refs:
            issues.append(f"supported claim has no evidence_refs: {claim.claim_id}")
        missing_claim = sorted(ref for ref in claim.evidence_refs if ref not in known)
        if missing_claim:
            issues.append(f"unresolvable claim refs for {claim.claim_id}: {missing_claim}")
    return {"issues": issues, "known_evidence_count": len(known)}


def _model_name(model: Any) -> str:
    value = getattr(model, "model_name", None)
    return str(value or type(model).__name__)


def load_project_dotenv() -> Path | None:
    """Load a simple project ``.env`` without overriding real environment vars."""
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[3] / ".env"]
    for path in candidates:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if not key or key in os.environ:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ[key] = value
        return path
    return None


def model_from_env() -> Any:
    load_project_dotenv()
    """Build an OpenAI-compatible PydanticAI model from environment variables."""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    model_name = os.environ.get("JUDGE_MODEL", "gpt-5.6-luna")
    base_url = os.environ.get("JUDGE_BASE_URL")
    api_key = os.environ.get("JUDGE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    provider = OpenAIProvider(base_url=base_url, api_key=api_key)
    return OpenAIChatModel(model_name, provider=provider)
