"""Score aggregation: per-skill results → case score → dataset summary.

The aggregation policy is pluggable. Defaults (HarnessEval-inspired):

* ``weighted_case_score`` — weighted mean of valid skill scores with
  optional gating: if a gate skill (e.g. "judgeable"/"validity") scores
  below a threshold the case score is zeroed (a video nobody can judge
  should not be rewarded).
* ``dataset_summary`` — mean/median case scores plus per-skill breakdowns.

Case packages can supply their own aggregation function; the report only
needs a ``case_score`` per case.
"""

from __future__ import annotations

import statistics
from typing import Any, Callable, Mapping

from .protocols import CaseEvidence, SkillResult

Aggregator = Callable[[CaseEvidence, Mapping[str, float]], float | None]


def _valid_score(result: SkillResult) -> float | None:
    if result.status not in {"ok", "skipped"}:
        return None
    score = result.score
    if score is None or not 0.0 <= score <= 1.0:
        return None
    return float(score)


def weighted_case_score(
    evidence: CaseEvidence,
    weights: Mapping[str, float],
    *,
    gate_skill: str | None = None,
    gate_threshold: float = 0.0,
) -> float | None:
    """Weighted mean of selected skill scores; optional validity gate."""
    pairs = []
    for skill_id, result in evidence.skill_results.items():
        score = _valid_score(result)
        if score is None:
            continue
        weight = weights.get(skill_id, 1.0)
        if weight <= 0:
            continue
        pairs.append((skill_id, score, weight))

    if not pairs:
        return None

    if gate_skill is not None:
        gate = evidence.skill_results.get(gate_skill)
        gate_score = _valid_score(gate) if gate is not None else None
        if gate_score is None or gate_score < gate_threshold:
            return 0.0

    total_weight = sum(w for _, _, w in pairs)
    return round(sum(s * w for _, s, w in pairs) / total_weight, 6)


def simple_mean_case_score(evidence: CaseEvidence, weights: Mapping[str, float]) -> float | None:
    """Unweighted mean of valid skill scores."""
    scores = [_valid_score(r) for r in evidence.skill_results.values()]
    scores = [s for s in scores if s is not None]
    if not scores:
        return None
    return round(statistics.mean(scores), 6)


def dataset_summary(
    cases: list[CaseEvidence],
    case_scores: Mapping[str, float | None],
    weights: Mapping[str, float],
) -> dict[str, Any]:
    valid = [s for s in case_scores.values() if s is not None]
    summary: dict[str, Any] = {
        "n_cases": len(cases),
        "n_scored": len(valid),
        "mean_case_score": round(statistics.mean(valid), 6) if valid else None,
        "median_case_score": round(statistics.median(valid), 6) if valid else None,
    }
    # per-skill aggregates across cases
    skill_scores: dict[str, list[float]] = {}
    for evidence in cases:
        for skill_id, result in evidence.skill_results.items():
            score = _valid_score(result)
            if score is None:
                continue
            skill_scores.setdefault(skill_id, []).append(score)
    summary["skills"] = {
        skill_id: {
            "mean": round(statistics.mean(scores), 6),
            "n_scored": len(scores),
        }
        for skill_id, scores in sorted(skill_scores.items())
    }
    return summary
