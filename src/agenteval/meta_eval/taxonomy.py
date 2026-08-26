"""Stable failure taxonomy for Judge reliability investigations."""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Iterable

from .gold import GoldJudgment


class FailureCode(StrEnum):
    RETRIEVAL_FAILURE = "R1 retrieval_failure"
    EVIDENCE_SELECTION_FAILURE = "R2 evidence_selection_failure"
    EVIDENCE_INTERPRETATION_FAILURE = "R3 evidence_interpretation_failure"
    EVIDENCE_HALLUCINATION = "R4 evidence_hallucination"
    EVIDENCE_STRENGTH_FAILURE = "R5 evidence_strength_failure"
    MISSING_EVIDENCE_FAILURE = "R6 missing_evidence_failure"
    CONTRADICTION_HANDLING_FAILURE = "R7 contradiction_handling_failure"
    RUBRIC_APPLICABILITY_FAILURE = "R8 rubric_applicability_failure"
    RUBRIC_ANCHOR_FAILURE = "R9 rubric_anchor_failure"
    REASONING_FAILURE = "R10 reasoning_failure"
    AGGREGATION_FAILURE = "R11 aggregation_failure"
    STOCHASTIC_INSTABILITY = "R12 stochastic_instability"
    UNCLASSIFIED = "unclassified"

    @property
    def code(self) -> str:
        return self.value.split(" ", 1)[0] if " " in self.value else self.value

    @property
    def label(self) -> str:
        return self.value.split(" ", 1)[1] if " " in self.value else self.value


def classify_failure(
    gold: GoldJudgment | None,
    judgment: dict[str, Any],
    *,
    available_evidence_ids: Iterable[str] = (),
    repeated_judgments: list[dict[str, Any]] | None = None,
) -> list[FailureCode]:
    """Conservative automatic triage; ambiguous cases stay unclassified.

    This is a diagnostic aid, not a deterministic replacement for human error
    analysis. It never infers evidence interpretation errors from score alone.
    """
    failures: list[FailureCode] = []
    # Include the current judgment. The runner calls this before appending the
    # observation to ``repeated_judgments``; checking only prior observations
    # misses instability first introduced by the current repeat.
    if repeated_judgments and _unstable([*repeated_judgments, judgment]):
        failures.append(FailureCode.STOCHASTIC_INSTABILITY)
    if gold is None:
        return failures
    refs = set(str(x) for x in judgment.get("evidence_refs", []))
    available = set(str(x) for x in available_evidence_ids)
    if refs - available:
        failures.append(FailureCode.EVIDENCE_HALLUCINATION)
    required = set(gold.required_evidence_refs)
    if required and not (required & refs):
        trajectory = judgment.get("provenance", {}).get("query_trajectory", [])
        searched_ids = {str(x) for step in trajectory for x in step.get("result_ids", [])}
        failures.append(FailureCode.RETRIEVAL_FAILURE if not (required & searched_ids)
                        else FailureCode.EVIDENCE_SELECTION_FAILURE)
    status = str(judgment.get("status", ""))
    if gold.expected_status in {"partially_supported", "unverified", "missing_evidence"} and status in {"supported", "scored"}:
        failures.append(FailureCode.MISSING_EVIDENCE_FAILURE)
    if gold.expected_status and status and status != gold.expected_status and not failures:
        failures.append(FailureCode.REASONING_FAILURE)
    return list(dict.fromkeys(failures))


def _unstable(judgments: list[dict[str, Any]]) -> bool:
    scores = [j.get("score") for j in judgments if j.get("score") is not None]
    statuses = [j.get("status") for j in judgments]
    # A nominal range of exactly 0.1 is not above the threshold; tolerate
    # binary floating-point representation such as 0.45 - 0.35.
    return len(set(statuses)) > 1 or (scores and max(scores) - min(scores) > 0.1 + 1e-12)
