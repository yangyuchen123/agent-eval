"""Deterministic RRD metrics, filtering and correlation-aware weighting."""
from __future__ import annotations
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Any
from .models import Rubric, RubricMetric

def normalized_text(text: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in text).split())

def text_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalized_text(left), normalized_text(right)).ratio()

def exact_duplicate_groups(rubrics: Sequence[Rubric]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    for rubric in rubrics: groups.setdefault(normalized_text(rubric.text), []).append(rubric.rubric_id)
    return [ids for ids in groups.values() if len(ids) > 1]

def behavioral_agreement(left: dict[str, int], right: dict[str, int]) -> float:
    ids = sorted(set(left) & set(right))
    return sum(int(left[x] == right[x]) for x in ids) / len(ids) if ids else 0.0

def majority_binary(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ones = sum(1 for v in values if int(v) == 1)
    zeros = len(values) - ones
    if ones > zeros:
        return 1
    if zeros > ones:
        return 0
    return None


def pairwise_agree(values: Sequence[int]) -> float | None:
    vals = [int(v) for v in values]
    pairs = [(vals[i], vals[j]) for i in range(len(vals)) for j in range(i + 1, len(vals))]
    if not pairs:
        return None
    return sum(a == b for a, b in pairs) / len(pairs)


def flip_metrics_from_repeats(repeats: Sequence[dict[str, dict[str, int]]], *, rubric_ids: Sequence[str] | None = None, response_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """Cell / row / set-level flip across repeated satisfaction matrices."""
    if not repeats:
        return {"repeat_count": 0}
    rubric_ids = list(rubric_ids or repeats[0].keys())
    response_ids = list(response_ids or sorted(next(iter(repeats[0].values())).keys()))
    cells = []
    for rid in rubric_ids:
        for sid in response_ids:
            vals = [int(rep.get(rid, {}).get(sid, 0)) for rep in repeats]
            cells.append({
                "rubric_id": rid,
                "response_id": sid,
                "scores": vals,
                "flip": len(set(vals)) > 1,
                "majority": majority_binary(vals),
                "pairwise_agree": pairwise_agree(vals),
            })
    rows = []
    for rid in rubric_ids:
        support = [sum(int(rep.get(rid, {}).get(sid, 0)) for sid in response_ids) for rep in repeats]
        rows.append({
            "rubric_id": rid,
            "support_counts": support,
            "flip_support_count": len(set(support)) > 1,
            "cell_flip_count": sum(1 for c in cells if c["rubric_id"] == rid and c["flip"]),
        })
    n_cells = len(cells) or 1
    agrees = [c["pairwise_agree"] for c in cells if c["pairwise_agree"] is not None]
    return {
        "repeat_count": len(repeats),
        "rubric_count": len(rubric_ids),
        "response_count": len(response_ids),
        "cell_count": len(cells),
        "cell_flip_count": sum(c["flip"] for c in cells),
        "cell_flip_rate": sum(c["flip"] for c in cells) / n_cells,
        "mean_cell_pairwise_agree": sum(agrees) / len(agrees) if agrees else None,
        "rubric_support_flip_count": sum(r["flip_support_count"] for r in rows),
        "rubric_support_flip_rate": sum(r["flip_support_count"] for r in rows) / (len(rows) or 1),
        "cells": cells,
        "rubrics": rows,
    }


def rubric_set_metrics(metrics: dict[str, RubricMetric]) -> dict[str, float]:
    if not metrics: return {"mean_support_rate": 0.0, "mean_discrimination": 0.0, "broad_candidate_rate": 0.0, "misalignment_candidate_rate": 0.0}
    values=list(metrics.values())
    return {"mean_support_rate":sum(x.support_rate for x in values)/len(values), "mean_discrimination":sum(x.discrimination for x in values)/len(values), "broad_candidate_rate":sum(x.broad_candidate for x in values)/len(values), "misalignment_candidate_rate":sum(x.misalignment_candidate for x in values)/len(values)}

def _prefer(new: Rubric, old: Rubric, metrics: dict[str, RubricMetric]) -> bool:
    a,b=metrics.get(new.rubric_id),metrics.get(old.rubric_id)
    return bool(a and b and a.discrimination > b.discrimination)

def semantic_filter(rubrics: Sequence[Rubric], matrix: dict[str, dict[str, int]], metrics: dict[str, RubricMetric], *, semantic_threshold=.92) -> tuple[list[Rubric], list[dict[str, Any]]]:
    """Drop exact/high-text-overlap duplicates only; behavioral similarity is not a drop rule."""
    kept=[]; dropped=[]
    for rubric in rubrics:
        prior=next((x for x in kept if normalized_text(x.text)==normalized_text(rubric.text)),None)
        reason='exact_duplicate'
        if prior is None:
            prior=next((x for x in kept if text_similarity(x.text,rubric.text)>=semantic_threshold),None)
            reason='semantic_redundancy'
        if prior is None:
            kept.append(rubric); continue
        if _prefer(rubric,prior,metrics):
            kept.remove(prior); kept.append(rubric)
            dropped.append({"rubric_id":prior.rubric_id,"reason":reason+"_lower_discrimination","compared_to":rubric.rubric_id})
        else:
            dropped.append({"rubric_id":rubric.rubric_id,"reason":reason,"compared_to":prior.rubric_id})
    return kept,dropped

def behavioral_redundancy_warnings(rubrics: Sequence[Rubric], matrix: dict[str, dict[str, int]], *, threshold=.90) -> list[dict[str, Any]]:
    warnings=[]
    for i,left in enumerate(rubrics):
        for right in rubrics[i+1:]:
            agreement=behavioral_agreement(matrix.get(left.rubric_id,{}),matrix.get(right.rubric_id,{}))
            if agreement>=threshold:
                warnings.append({"rubric_id":left.rubric_id,"compared_to":right.rubric_id,"reason":"behaviorally_redundant_warning","behavioral_agreement":agreement})
    return warnings

def _mat_inverse(a: list[list[float]]) -> list[list[float]]:
    n=len(a); aug=[row[:] + [1.0 if i==j else 0.0 for j in range(n)] for i,row in enumerate(a)]
    for col in range(n):
        pivot=max(range(col,n),key=lambda r:abs(aug[r][col]))
        if abs(aug[pivot][col])<1e-10: raise ValueError('singular matrix')
        aug[col],aug[pivot]=aug[pivot],aug[col]
        scale=aug[col][col]; aug[col]=[x/scale for x in aug[col]]
        for r in range(n):
            if r==col: continue
            scale=aug[r][col]
            aug[r]=[x-scale*y for x,y in zip(aug[r],aug[col])]
    return [row[n:] for row in aug]

def correlation_aware_weights(rubrics: Sequence[Rubric], matrix: dict[str, dict[str, int]], metrics: dict[str, RubricMetric], ridge=.05) -> dict[str,float]:
    """Approximate RRD precision/whitened weighting without numpy.

    Uses absolute preference edge as informativeness and a ridge-regularized
    covariance inverse to reduce weight for highly correlated criteria. It is
    a weighting diagnostic, not a reason to delete behaviorally correlated
    rubrics.
    """
    ids=[r.rubric_id for r in rubrics]; n=len(ids)
    if not n: return {}
    response_ids=sorted(next(iter(matrix.values())).keys()) if matrix else []
    cols=[[float(matrix.get(rid,{}).get(x,0)) for x in response_ids] for rid in ids]
    means=[sum(c)/len(c) if c else 0.0 for c in cols]
    cov=[[0.0]*n for _ in range(n)]
    denom=max(1,len(response_ids)-1)
    for i in range(n):
        for j in range(n): cov[i][j]=sum((cols[i][k]-means[i])*(cols[j][k]-means[j]) for k in range(len(response_ids)))/denom + (ridge if i==j else 0.0)
    try: inv=_mat_inverse(cov)
    except ValueError: return {rid:1.0/n for rid in ids}
    signal=[max(0.0,abs(metrics.get(rid,RubricMetric(0,0,0,None,0,0,0,0)).discrimination)) for rid in ids]
    if sum(signal)==0: signal=[1.0]*n
    raw=[max(0.0,sum(inv[i][j]*signal[j] for j in range(n))) for i in range(n)]
    if sum(raw)==0: raw=[1.0]*n
    total=sum(raw)
    return {rid:raw[i]/total for i,rid in enumerate(ids)}

# Backward-compatible name for callers of the first draft. Behavioral
# agreement is deliberately not a deletion criterion anymore.
def filter_candidates(rubrics, matrix, metrics, *, behavioral_threshold=.90, semantic_threshold=.92, enable_semantic_filter=True, prefer_discrimination=True):
    return semantic_filter(rubrics, matrix, metrics, semantic_threshold=semantic_threshold) if enable_semantic_filter else (list(rubrics), [])
