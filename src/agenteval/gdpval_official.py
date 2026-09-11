"""GDPval official rubric loading and Proxy Gold scoring helpers.

Official ``score`` is an item weight, not a gold label.  A Proxy Gold label is
a frozen Judge's 0/1 on that official item.  This module never writes Human
Gold and does not live under ``meta_eval/gold/``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

OFFICIAL_BINARY_ANCHORS = [
    {
        "score": 0.0,
        "label": "not_satisfied",
        "description": "The criterion is not satisfied, or direct evidence is insufficient.",
    },
    {
        "score": 1.0,
        "label": "satisfied",
        "description": "The criterion is satisfied by direct, case-relevant evidence from the supplied artifact.",
    },
]


def load_official_criteria(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        items = (
            payload.get("rubric_json")
            or payload.get("rubric_items")
            or payload.get("criteria")
            or payload.get("rubric")
            or []
        )
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    criteria = [dict(x) for x in items if isinstance(x, dict)]
    if not criteria:
        raise ValueError(f"no official rubric criteria in {path}")
    return criteria


def official_weight(item: Mapping[str, Any]) -> float:
    raw = item.get("official_weight", item.get("score", 1.0))
    return float(raw if raw is not None else 1.0)


def criterion_id(item: Mapping[str, Any]) -> str:
    return str(
        item.get("criterion_id")
        or item.get("rubric_id")
        or item.get("rubric_item_id")
        or item.get("id")
        or ""
    ).strip()


def criterion_text(item: Mapping[str, Any]) -> str:
    return str(
        item.get("criterion")
        or item.get("text")
        or item.get("question")
        or item.get("description")
        or ""
    ).strip()


def official_questions_for_b_judge(criteria: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Binary Judge questions.  Official points stay in ``official_weight``.

    Judge aggregation remains the unweighted mean, matching A/C/D one-shot B.
    Weighted GDPval overall is computed offline from the 0/1 vector.
    """
    questions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in criteria:
        cid = criterion_id(item)
        text = criterion_text(item)
        if not cid or cid == "None":
            raise ValueError(f"official criterion missing id: {item!r}")
        if not text:
            raise ValueError(f"official criterion {cid} has empty text")
        if cid in seen:
            raise ValueError(f"duplicate official criterion id: {cid}")
        seen.add(cid)
        questions.append(
            {
                "id": cid,
                "question": text,
                "description": text,
                "weight": 1.0,
                "official_weight": official_weight(item),
                "score_anchors": list(OFFICIAL_BINARY_ANCHORS),
                "evidence": "artifact",
            }
        )
    return questions


def weights_by_id(questions: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    return {str(q["id"]): official_weight(q) for q in questions}


def unweighted_mean(scores: Iterable[float]) -> float | None:
    values = [float(x) for x in scores]
    if not values:
        return None
    return sum(values) / len(values)


def weighted_overall(score_by_id: Mapping[str, float], weights: Mapping[str, float]) -> float | None:
    """GDPval-style overall: sum(s_i * w_i) / sum(w_i).  Empty xlsx is 0, not None."""
    if not weights:
        return None
    numerator = 0.0
    denominator = 0.0
    for cid, weight in weights.items():
        numerator += float(score_by_id.get(cid, 0.0)) * float(weight)
        denominator += float(weight)
    if denominator == 0:
        return None
    return numerator / denominator


def majority_binary(scores: Sequence[float], *, min_votes: int | None = None) -> int | None:
    values = [int(round(float(x))) for x in scores]
    if not values:
        return None
    need = len(values) if min_votes is None else min_votes
    if values.count(1) >= need:
        return 1
    if values.count(0) >= need:
        return 0
    ones = values.count(1)
    zeros = len(values) - ones
    if ones == zeros:
        return None
    return 1 if ones > zeros else 0


def proxy_gold_labels(repeats: Sequence[Mapping[str, float]], weights: Mapping[str, float]) -> dict[str, Any]:
    """Aggregate repeated 0/1 vectors into one Proxy Gold record for an attempt."""
    ids = list(weights)
    by_id: dict[str, list[float]] = {cid: [] for cid in ids}
    for score_map in repeats:
        for cid in ids:
            if cid in score_map and score_map[cid] is not None:
                by_id[cid].append(float(score_map[cid]))
    majority = {cid: majority_binary(vals) for cid, vals in by_id.items()}
    usable = {cid: (0.0 if val is None else float(val)) for cid, val in majority.items()}
    return {
        "n_repeats": len(repeats),
        "criterion_count": len(ids),
        "majority_by_id": majority,
        "flip_ids": [cid for cid, vals in by_id.items() if len(set(int(round(v)) for v in vals)) > 1],
        "unweighted_majority_mean": unweighted_mean(usable[cid] for cid in ids),
        "weighted_majority_overall": weighted_overall(usable, weights),
        "weight_sum": sum(weights.values()),
    }
