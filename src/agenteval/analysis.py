"""Rubric Diagnostics: is this rubric question worth keeping?

Phase 3.1 — measurement science before automation. We do NOT generate
rubrics here; we tell a human which questions carry signal and why.

For every question of a rubric, across evaluation history:

* ``n / mean / std / variance``          — spread of scores
* ``entropy``                            — discrete distribution shape
* ``difficulty``                         — mean (IRT-style: high = easy)
* ``discrimination``                     — corr(question, total score);
                                          an IRT-style item-quality proxy:
                                          good questions separate good
                                          agents from bad ones
* ``distribution``                       — counts per score level
* ``recommendation``                     — rule-based verdict

Low variance is ambiguous (everyone is good / rubric too easy / judge
leniency) — discrimination disambiguates: a question that never varies
AND does not track the overall score carries no information.

Judge reliability (Phase 3.2 inputs) is stubbed here as
``judge_self_consistency``: same (case, skill) judged repeatedly →
std of scores. Needs multi-run or repeated-judge data.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Iterable, Mapping

from .history import EvalRecord, by_rubric, question_values

RECOMMENDATION_THRESHOLDS = {
    "min_n": 3,
    "ceiling_mean": 0.9,      # mean above → everyone passes
    "floor_mean": 0.2,        # mean below → everyone fails
    "std_flat": 0.05,         # std below → no spread
    "corr_noise": 0.3,        # |corr| below → weakly related to overall
}


# ------------------------------------------------------------ metrics ------

def _entropy(values: list[float]) -> float:
    if not values:
        return 0.0
    counts: dict[float, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    n = len(values)
    h = -sum((c / n) * math.log2(c / n) for c in counts.values())
    # normalize by log2(n) so entropy ∈ [0, 1]
    return round(h / math.log2(n), 4) if n > 1 else 0.0


def _pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) < 2 or len(x) != len(y):
        return None
    mx, my = statistics.mean(x), statistics.mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) *
                    sum((b - my) ** 2 for b in y))
    if den == 0:
        return None
    return round(num / den, 4)


def question_metrics(records: list[EvalRecord],
                     question_id: str) -> dict[str, Any]:
    """Per-question diagnostics across records (same rubric)."""
    values = question_values(records, question_id)
    totals = [r.score for r in records
              if r.score is not None and question_values([r], question_id)]
    totals = [r.score for r in records if r.score is not None]

    if not values:
        return {"question_id": question_id, "n": 0}

    mean = statistics.mean(values)
    std = statistics.pstdev(values) if len(values) > 1 else 0.0
    distribution: dict[str, int] = {}
    for v in values:
        key = f"{v:.2f}"
        distribution[key] = distribution.get(key, 0) + 1

    # discrimination: corr(question, total) over records that have both
    pairs = [(v, t) for r, v, t in
             ((r, (r.subscores or {}).get(question_id), r.score)
              for r in records)
             if v is not None and t is not None]
    corr = _pearson([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) >= 2 else None

    return {
        "question_id": question_id,
        "n": len(values),
        "mean": round(mean, 4),
        "std": round(std, 4),
        "variance": round(std ** 2, 4),
        "entropy": _entropy(values),
        "difficulty": round(mean, 4),          # IRT-ish: high = easy
        "discrimination": corr,
        "distribution": distribution,
        "recommendation": recommend(mean, std, corr, len(values)),
    }


def recommend(mean: float, std: float, corr: float | None,
              n: int) -> dict[str, Any]:
    """Rule-based verdict for one question."""
    t = RECOMMENDATION_THRESHOLDS
    if n < t["min_n"]:
        return {"action": "insufficient_data",
                "message": f"only {n} records — collect more before judging"}
    if std < t["std_flat"] and mean > t["ceiling_mean"]:
        return {"action": "ceiling",
                "message": "everyone scores near max — no discrimination; "
                           "tighten anchors or remove"}
    if std < t["std_flat"] and mean < t["floor_mean"]:
        return {"action": "floor",
                "message": "everyone fails — consider lowering difficulty"}
    if corr is None:
        return {"action": "review",
                "message": "spread exists but no correlation computable"}
    if corr < 0:
        return {"action": "noisy",
                "message": f"corr(question,total)={corr} is NEGATIVE — "
                           "high-scoring agents score lower here; anchors "
                           "may be inverted, review"}
    if abs(corr) < t["corr_noise"]:
        return {"action": "noisy",
                "message": f"spread exists but corr(question,total)={corr} — "
                           "weakly related to overall; review anchors/evidence"}
    return {"action": "keep",
            "message": f"healthy discriminator (corr={corr}) — keep"}


# ------------------------------------------------------------- report ------

def rubric_diagnostics(records: list[EvalRecord],
                       rubric_id: str,
                       version: str | None = None) -> dict[str, Any]:
    """Full diagnostics report for one rubric (all versions or pinned)."""
    recs = by_rubric(records, rubric_id, version)
    qids: list[str] = []
    for r in recs:
        for qid in (r.subscores or {}):
            if qid not in qids:
                qids.append(qid)
    questions = {qid: question_metrics(recs, qid) for qid in qids}
    return {
        "rubric_id": rubric_id,
        "rubric_version": version,
        "n_records": len(recs),
        "n_questions": len(qids),
        "questions": questions,
        "summary": {
            "keep": sum(1 for q in questions.values()
                        if q["recommendation"]["action"] == "keep"),
            "review": sum(1 for q in questions.values()
                          if q["recommendation"]["action"] in
                          ("ceiling", "floor", "noisy")),
            "insufficient_data": sum(
                1 for q in questions.values()
                if q["recommendation"]["action"] == "insufficient_data"),
        },
    }


# -------------------------------------------------- judge reliability ------

def judge_self_consistency(records: list[EvalRecord]) -> dict[str, Any]:
    """Std of scores when the same (case, skill) was judged repeatedly.

    Requires multi-run or repeated-judge data; empty otherwise.
    """
    grouped: dict[tuple[str, str], list[float]] = {}
    for r in records:
        if r.score is None:
            continue
        key = (r.case_id, r.skill_id)
        grouped.setdefault(key, []).append(float(r.score))
    repeated = {k: v for k, v in grouped.items() if len(v) > 1}
    stds = [statistics.pstdev(v) for v in repeated.values()]
    return {
        "n_repeated": len(repeated),
        "mean_std": round(statistics.mean(stds), 4) if stds else None,
        "max_std": round(max(stds), 4) if stds else None,
        "by_item": {f"{k[0]}::{k[1]}": round(statistics.pstdev(v), 4)
                    for k, v in sorted(repeated.items())},
    }


# -------------------------------------------------------------- render -----

def render_diagnostics(report: Mapping[str, Any]) -> str:
    """Human-readable markdown report."""
    lines = [
        f"# Rubric diagnostics — {report['rubric_id']}",
        f"version: {report.get('rubric_version') or 'all'}  "
        f"records: {report['n_records']}",
        "",
        "| question | n | mean | std | entropy | corr(θ,total) | verdict |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for qid, q in report["questions"].items():
        corr = q["discrimination"]
        corr_s = "—" if corr is None else f"{corr:.2f}"
        verdict = q["recommendation"]["action"]
        lines.append(
            f"| {qid} | {q['n']} | {q['mean']:.2f} | {q['std']:.2f} "
            f"| {q['entropy']:.2f} | {corr_s} | {verdict} |")
    lines.append("")
    for qid, q in report["questions"].items():
        rec = q["recommendation"]
        if rec["action"] != "keep":
            lines.append(f"- **{qid}** [{rec['action']}]: {rec['message']}")
    return "\n".join(lines)
