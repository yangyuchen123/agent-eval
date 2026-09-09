"""Distributional audit of rubric classifications.

This module compares generated rubric property distributions with a Gold
reference distribution. It is descriptive triage, not a rubric correctness
classifier: being unusual relative to Gold is a review signal, not an error.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ACTIVE_AXES = (
    "grounding", "scope", "evidence_source", "atomicity", "hardness",
    "judgment_type", "capability",
)
DEFAULT_PAIRS = (
    ("grounding", "scope"),
    ("scope", "evidence_source"),
    ("scope", "capability"),
    ("grounding", "capability"),
    ("hardness", "judgment_type"),
    ("atomicity", "capability"),
)


def _value(row: Mapping[str, Any], axis: str) -> str:
    value = row.get(axis, "unknown")
    if axis == "capability":
        if isinstance(value, Mapping):
            value = value.get("primary", value.get("primary_capability", "unknown"))
        elif not value:
            value = "unknown"
    return str(value or "unknown")


def _counts(rows: Sequence[Mapping[str, Any]], axis: str) -> Counter[str]:
    return Counter(_value(row, axis) for row in rows)


def _prob(count: int, total: int, categories: int, alpha: float) -> float:
    return (count + alpha) / (total + alpha * categories)


def js_divergence(gold: Counter[str], other: Counter[str], *, alpha: float = 0.5) -> float:
    """JSD in nats, using the union support and symmetric smoothing."""
    categories = sorted(set(gold) | set(other))
    if not categories:
        return 0.0
    ng, no = sum(gold.values()), sum(other.values())
    pg = {x: _prob(gold[x], ng, len(categories), alpha) for x in categories}
    po = {x: _prob(other[x], no, len(categories), alpha) for x in categories}
    return 0.5 * sum(pg[x] * math.log(pg[x] / ((pg[x] + po[x]) / 2)) for x in categories) + 0.5 * sum(po[x] * math.log(po[x] / ((pg[x] + po[x]) / 2)) for x in categories)


def _distribution(counter: Counter[str]) -> dict[str, Any]:
    total = sum(counter.values())
    return {k: {"count": v, "rate": v / total if total else 0.0} for k, v in sorted(counter.items())}


def _pair_key(row: Mapping[str, Any], pair: tuple[str, str]) -> str:
    return f"{_value(row, pair[0])} × {_value(row, pair[1])}"


def standardized_residuals(gold: Sequence[Mapping[str, Any]], other: Sequence[Mapping[str, Any]], axis: str, *, alpha: float = 0.5) -> list[dict[str, Any]]:
    """Compare generated counts to expected counts under Gold proportions.

    This is a descriptive Pearson standardized residual. It is not reported as
    a significance test, especially for this small pilot.
    """
    gc = _counts(gold, axis)
    oc = _counts(other, axis)
    categories = sorted(set(gc) | set(oc))
    ng, no = len(gold), len(other)
    # smoothed Gold proportions make unseen Gold categories representable.
    denom = ng + alpha * len(categories)
    result = []
    for category in categories:
        expected = no * (gc[category] + alpha) / denom
        residual = (oc[category] - expected) / math.sqrt(expected) if expected > 0 else 0.0
        result.append({"category": category, "observed": oc[category], "expected_from_gold": expected, "standardized_residual": residual})
    return sorted(result, key=lambda x: abs(x["standardized_residual"]), reverse=True)


def pair_residuals(gold: Sequence[Mapping[str, Any]], other: Sequence[Mapping[str, Any]], pair: tuple[str, str], *, alpha: float = 0.5) -> list[dict[str, Any]]:
    gc = Counter(_pair_key(row, pair) for row in gold)
    oc = Counter(_pair_key(row, pair) for row in other)
    categories = sorted(set(gc) | set(oc))
    ng, no = len(gold), len(other)
    denom = ng + alpha * len(categories)
    result = []
    for category in categories:
        expected = no * (gc[category] + alpha) / denom
        residual = (oc[category] - expected) / math.sqrt(expected) if expected > 0 else 0.0
        result.append({"category": category, "observed": oc[category], "expected_from_gold": expected, "standardized_residual": residual})
    return sorted(result, key=lambda x: abs(x["standardized_residual"]), reverse=True)


def rubric_suspicion(row: Mapping[str, Any], gold: Sequence[Mapping[str, Any]], *, pairs: Sequence[tuple[str, str]] = DEFAULT_PAIRS, alpha: float = 0.5) -> dict[str, Any]:
    """Return a review-priority score; high means unusual relative to Gold."""
    scores: dict[str, float] = {}
    for axis in ACTIVE_AXES:
        gc = _counts(gold, axis)
        categories = set(gc) | {_value(row, axis)}
        p = _prob(gc[_value(row, axis)], len(gold), len(categories), alpha)
        scores[axis] = -math.log(p)
    pair_scores: dict[str, float] = {}
    for pair in pairs:
        gc = Counter(_pair_key(x, pair) for x in gold)
        categories = set(gc) | {_pair_key(row, pair)}
        p = _prob(gc[_pair_key(row, pair)], len(gold), len(categories), alpha)
        pair_scores[f"{pair[0]}×{pair[1]}"] = -math.log(p)
    # Keep marginal and interaction components separately. The total is a
    # triage score, not a probability and not an error score.
    marginal = sum(scores.values()) / len(scores)
    interaction = sum(pair_scores.values()) / len(pair_scores) if pair_scores else 0.0
    return {"marginal_surprisal": marginal, "pairwise_surprisal": interaction, "suspicion_score": marginal + 0.5 * interaction, "axis_surprisal": scores, "pair_surprisal": pair_scores}


def analyze(rows: Iterable[Mapping[str, Any]], *, gold_condition: str = "Gold", generated_conditions: Sequence[str] = ("A", "C", "D"), alpha: float = 0.5, pairs: Sequence[tuple[str, str]] = DEFAULT_PAIRS) -> dict[str, Any]:
    rows = [dict(r) for r in rows]
    gold = [r for r in rows if str(r.get("condition")) == gold_condition]
    result: dict[str, Any] = {
        "schema_version": "agenteval.rubric_distribution_audit.v1",
        "gold_condition": gold_condition,
        "generated_conditions": list(generated_conditions),
        "active_axes": list(ACTIVE_AXES),
        "smoothing_alpha": alpha,
        "interpretation": "Suspicion is a review-priority signal, not a rubric error label. Applicability is intentionally excluded from active analysis.",
        "gold_counts": {axis: _distribution(_counts(gold, axis)) for axis in ACTIVE_AXES},
        "conditions": {},
    }
    for condition in generated_conditions:
        other = [r for r in rows if str(r.get("condition")) == condition]
        axes = {}
        for axis in ACTIVE_AXES:
            axes[axis] = {
                "gold_vs_condition_jsd_nats": js_divergence(_counts(gold, axis), _counts(other, axis), alpha=alpha),
                "gold": _distribution(_counts(gold, axis)),
                "condition": _distribution(_counts(other, axis)),
                "standardized_residuals": standardized_residuals(gold, other, axis, alpha=alpha),
            }
        pairs_result = {f"{a}×{b}": pair_residuals(gold, other, (a, b), alpha=alpha) for a, b in pairs}
        review_rows = []
        for row in other:
            review_rows.append({"condition": condition, "criterion_id": row.get("criterion_id"), "criterion": row.get("criterion", ""), **rubric_suspicion(row, gold, pairs=pairs, alpha=alpha)})
        review_rows.sort(key=lambda x: x["suspicion_score"], reverse=True)
        result["conditions"][condition] = {
            "criterion_count": len(other),
            "axes": axes,
            "pairwise_standardized_residuals": pairs_result,
            "rubric_suspicion_ranking": review_rows,
        }
    return result


def render_report(result: Mapping[str, Any], *, top_n: int = 10) -> str:
    generated = list(result.get("generated_conditions") or [])
    header = "| Axis | " + " | ".join(generated) + " |"
    divider = "|---|" + "---:|" * len(generated)
    lines = ["# Rubric Distribution Audit", "", "本报告是描述性统计与人工复核优先级工具，不是 rubric correctness classifier。", f"高 suspicion 只表示相对 `{result.get('gold_condition')}` 分布不常见，不表示 rubric 错误。", "", "## 1. Axis-level Jensen–Shannon divergence", "", "JSD 使用平滑后的类别分布，单位为 nats；0 表示分布一致，越大表示偏离越大。", "", header, divider]
    for axis in result["active_axes"]:
        vals = []
        for c in generated:
            vals.append(f"{result['conditions'].get(c, {}).get('axes', {}).get(axis, {}).get('gold_vs_condition_jsd_nats', 0):.4f}")
        lines.append(f"| {axis} | " + " | ".join(vals) + " |")
    for condition in result["generated_conditions"]:
        data = result["conditions"].get(condition, {})
        lines += ["", f"## 2. {condition}: largest standardized residuals", "", "Residuals are descriptive; no p-value or significance claim is made.", ""]
        for axis in result["active_axes"]:
            top = data.get("axes", {}).get(axis, {}).get("standardized_residuals", [])[:3]
            if top:
                formatted = "; ".join(f"{x['category']} (obs={x['observed']}, exp={x['expected_from_gold']:.2f}, r={x['standardized_residual']:.2f})" for x in top)
                lines.append(f"- **{axis}**: {formatted}")
        lines += ["", f"### {condition} rubric review priority (top {top_n})", "", "| Rank | Criterion | Suspicion | Main unusual axes |", "|---:|---|---:|---|"]
        for i, item in enumerate(data.get("rubric_suspicion_ranking", [])[:top_n], 1):
            axes = sorted(item.get("axis_surprisal", {}).items(), key=lambda x: x[1], reverse=True)[:2]
            label = ", ".join(f"{a}={v:.2f}" for a, v in axes)
            criterion = str(item.get("criterion") or item.get("criterion_id") or "")[:110].replace("|", "/")
            lines.append(f"| {i} | {criterion} | {item['suspicion_score']:.2f} | {label} |")
    lines += ["", "## 3. Interpretation boundary", "", "- Gold is a reference distribution, not a normative truth for every generated criterion.", "- A task-supported criterion absent from Gold can be a valid extra, so residuals must be manually reviewed.", "- This analysis excludes the deprecated applicability axis and does not use Judge predictions, Gold satisfaction labels, or run outcomes.", "- Small-sample JSD/residual values are screening signals, not stable population estimates.", ""]
    return "\n".join(lines)


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_outputs(
    rows: Iterable[Mapping[str, Any]],
    out_dir: str | Path,
    *,
    top_n: int = 10,
    gold_condition: str = "Gold",
    generated_conditions: Sequence[str] = ("A", "C", "D"),
) -> dict[str, Path]:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    result = analyze(rows, gold_condition=gold_condition, generated_conditions=generated_conditions)
    json_path = out / "rubric_distribution_audit.json"
    report_path = out / "RUBRIC_DISTRIBUTION_AUDIT_REPORT.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(render_report(result, top_n=top_n) + "\n", encoding="utf-8")
    return {"json": json_path, "report": report_path}
