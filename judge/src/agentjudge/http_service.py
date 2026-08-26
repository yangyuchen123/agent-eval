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
from .models import JudgeRequest, QuestionJudgment
from .service import QuestionJudgeService


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
        service = QuestionJudgeService(self.model, evidence)
        judgment = await service.evaluate(request)
        integrity = validate_judgment(judgment, evidence)
        provenance = {
            "model": _model_name(self.model),
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


def default_evidence_factory(request: JudgeRequest) -> EvidenceCatalog:
    """Resolve only an explicit local attempt directory from ``trace_ref``.

    Remote trace retrieval is intentionally outside this service. Callers that
    use another runtime can inject ``evidence_factory`` without changing the
    Judge contract.
    """
    ref = request.trace_ref
    if isinstance(ref, dict):
        ref = ref.get("attempt_dir") or ref.get("path") or ref.get("trace_path")
    if not ref:
        return EvidenceCatalog()
    path = Path(str(ref)).expanduser()
    if path.is_file():
        path = path.parent
    if not path.is_dir():
        raise ValueError(f"trace_ref is not an attempt directory: {ref}")
    return EvidenceCatalog.from_attempt_dir(path)


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
