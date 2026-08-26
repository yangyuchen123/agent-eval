"""Metrics for retrieval, claims, score agreement and stability."""
from __future__ import annotations

import math
import statistics
from typing import Any, Iterable


def score_summary(scores: Iterable[float]) -> dict[str, float | int | None]:
    values = [float(x) for x in scores]
    if not values:
        return {"n": 0, "mean": None, "std": None, "min": None, "max": None}
    return {"n": len(values), "mean": statistics.mean(values), "std": statistics.stdev(values) if len(values) > 1 else 0.0, "min": min(values), "max": max(values)}


def evidence_jaccard(left: Iterable[str], right: Iterable[str]) -> float | None:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def retrieval_metrics(required: Iterable[str], selected: Iterable[str], available: Iterable[str] = ()) -> dict[str, float | None]:
    req, got, avail = set(required), set(selected), set(available)
    return {
        "required_evidence_recall": (len(req & got) / len(req)) if req else None,
        "evidence_precision": (len(got & avail) / len(got)) if got else None,
        "evidence_recall": (len(req & got) / len(req)) if req else None,
    }


def score_metrics(predicted: Iterable[float], expected: Iterable[float]) -> dict[str, float | None]:
    pairs = [(float(a), float(b)) for a, b in zip(predicted, expected)]
    if not pairs:
        return {"mae": None, "pearson": None, "spearman": None, "pairwise_ranking_accuracy": None, "threshold_agreement": None}
    p, g = zip(*pairs)
    mae = statistics.mean(abs(a - b) for a, b in pairs)
    return {
        "mae": mae,
        "pearson": _pearson(p, g),
        "spearman": _pearson(_ranks(p), _ranks(g)),
        "pairwise_ranking_accuracy": _pairwise_accuracy(p, g),
        "threshold_agreement": statistics.mean((a >= 0.5) == (b >= 0.5) for a, b in pairs),
    }


def claim_agreement(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    a = {(str(c.get("claim_id")), str(c.get("status"))) for c in left.get("findings", []) if isinstance(c, dict)}
    b = {(str(c.get("claim_id")), str(c.get("status"))) for c in right.get("findings", []) if isinstance(c, dict)}
    return evidence_jaccard(a, b)


def stability_metrics(judgments: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [j["score"] for j in judgments if j.get("score") is not None]
    statuses = [j.get("status") for j in judgments]
    jaccards = []
    for i, left in enumerate(judgments):
        for right in judgments[i + 1:]:
            jaccards.append(evidence_jaccard(left.get("evidence_refs", []), right.get("evidence_refs", [])))
    score_pairs = [
        (scores[i], scores[j])
        for i in range(len(scores)) for j in range(i + 1, len(scores))
    ]
    return {
        "score": score_summary(scores),
        "score_distribution": dict(_counts(_score_key(score) for score in scores)),
        "exact_score_agreement": (len(set(scores)) == 1) if scores else None,
        "pairwise_score_agreement": (
            statistics.mean(left == right for left, right in score_pairs)
            if score_pairs else None
        ),
        "exact_status_agreement": (len(set(statuses)) == 1) if statuses else None,
        "pairwise_evidence_jaccard": statistics.mean(jaccards) if jaccards else None,
        "exact_claim_identity_agreement": statistics.mean([claim_agreement(judgments[i], judgments[j]) for i in range(len(judgments)) for j in range(i + 1, len(judgments))]) if len(judgments) > 1 else None,
    }



def compare_judgment_sets(baseline: list[dict[str, Any]], perturbed: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare two repeated-run conditions without pretending runs are paired."""
    base_scores = [float(x["score"]) for x in baseline if x.get("score") is not None]
    pert_scores = [float(x["score"]) for x in perturbed if x.get("score") is not None]
    cross_jaccards = [
        evidence_jaccard(left.get("evidence_refs", []), right.get("evidence_refs", []))
        for left in baseline for right in perturbed
    ]
    return {
        "baseline_score": score_summary(base_scores),
        "perturbed_score": score_summary(pert_scores),
        "mean_score_delta": (statistics.mean(pert_scores) - statistics.mean(base_scores))
            if base_scores and pert_scores else None,
        "baseline_statuses": dict(_counts(str(x.get("status")) for x in baseline)),
        "perturbed_statuses": dict(_counts(str(x.get("status")) for x in perturbed)),
        "cross_condition_evidence_jaccard": statistics.mean(cross_jaccards) if cross_jaccards else None,
        "synthetic_evidence_selected": sorted({
            str(ref) for item in perturbed for ref in item.get("evidence_refs", [])
            if str(ref).startswith("meta_eval.synthetic:")
        }),
    }


def _score_key(value: float) -> str:
    return f"{float(value):g}"


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result

def _pearson(a: Iterable[float], b: Iterable[float]) -> float | None:
    x, y = list(a), list(b)
    if len(x) < 2 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    mx, my = statistics.mean(x), statistics.mean(y)
    den = math.sqrt(sum((i - mx) ** 2 for i in x) * sum((i - my) ** 2 for i in y))
    return sum((i - mx) * (j - my) for i, j in zip(x, y)) / den if den else None


def _ranks(values: Iterable[float]) -> list[float]:
    data = list(values)
    return [1 + sum(other < value for other in data) + (sum(other == value for other in data) - 1) / 2 for value in data]


def _pairwise_accuracy(predicted: Iterable[float], expected: Iterable[float]) -> float | None:
    p, g = list(predicted), list(expected)
    pairs = [(i, j) for i in range(len(p)) for j in range(i + 1, len(p)) if g[i] != g[j]]
    if not pairs:
        return None
    return sum((p[i] - p[j]) * (g[i] - g[j]) > 0 for i, j in pairs) / len(pairs)
