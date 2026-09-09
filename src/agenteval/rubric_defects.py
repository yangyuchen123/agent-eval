"""Rubric Defect Attribution.

This role turns rubric analyses into reviewable defect *candidates*. It keeps
set-level, criterion-level, and execution-level findings separate and never
silently converts a distribution anomaly or Judge disagreement into a rubric
error.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

CONDITIONS = ("A", "C", "D")
VAGUE_TERMS = {"frequent", "often", "properly", "appropriate", "reasonable", "concise", "consistent", "enough", "broad", "significant", "clearly", "professional", "usable"}
NEGATIVE_MARKERS = ("does not", "do not", "never", "avoid", "without", "only", "must not", "not use", "no ")


def criterion_text(row: Mapping[str, Any], generated: Mapping[str, Any] | None = None) -> str:
    return str((generated or {}).get("criterion") or row.get("criterion") or "")


def _caps(row: Mapping[str, Any]) -> set[str]:
    cap = row.get("capability") or {}
    if isinstance(cap, Mapping):
        values = [cap.get("primary"), *(cap.get("secondary") or [])]
    else:
        values = [cap]
    return {str(x) for x in values if x}


def _primary(row: Mapping[str, Any]) -> str:
    cap = row.get("capability") or {}
    if isinstance(cap, Mapping):
        return str(cap.get("primary") or "unknown")
    return str(cap or "unknown")


def _record(level: str, condition: str, defect_type: str, severity: str, *, criterion_id: str | None = None, evidence: list[str] | None = None, repairability: str = "review", recommended_repair: str = "inspect", confidence: str = "medium") -> dict[str, Any]:
    return {
        "level": level,
        "condition": condition,
        "defect_type": defect_type,
        "severity": severity,
        "criterion_id": criterion_id,
        "evidence": evidence or [],
        "repairability": repairability,
        "recommended_repair": recommended_repair,
        "confidence": confidence,
        "status": "candidate",
    }


def _load_generated(path: str | Path | None, condition_alias: str | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    if not path:
        return {}
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        condition = condition_alias or str(obj.get("condition", ""))
        generated = obj.get("generated") or {}
        for item in generated.get("criteria", []) if isinstance(generated, Mapping) else []:
            result[(condition, str(item.get("criterion_id")))] = item
    return result


def _load_stability(path: str | Path | None) -> Mapping[str, Any] | None:
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else None


def _stability_records(stability: Mapping[str, Any], condition: str) -> list[dict[str, Any]]:
    data = (stability.get("conditions") or {}).get(condition) if isinstance(stability.get("conditions"), Mapping) else None
    return list((data or {}).get("by_criterion") or [])


def analyze(rows: Iterable[Mapping[str, Any]], *, generated_files: Mapping[str, str | Path] | None = None, stability_file: str | Path | None = None, gold_condition: str = "Gold") -> dict[str, Any]:
    rows = [dict(x) for x in rows]
    generated: dict[tuple[str, str], dict[str, Any]] = {}
    for condition, path in (generated_files or {}).items():
        # The historical generation files use descriptive condition names
        # (task_only/retrieved_human_rubric/global_profile), while the
        # classification table uses A/C/D. The caller's key is canonical.
        generated.update(_load_generated(path, condition_alias=str(condition)))
    stability = _load_stability(stability_file)
    by_condition = {c: [r for r in rows if str(r.get("condition")) == c] for c in {str(r.get("condition")) for r in rows}}
    gold = by_condition.get(gold_condition, [])
    gold_caps = {_primary(r) for r in gold}
    output: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"set_level": [], "criterion_level": [], "execution_level": []}

    for condition, current in sorted(by_condition.items()):
        if condition == gold_condition:
            continue
        current_caps = {_primary(r) for r in current}
        missing = sorted(gold_caps - current_caps)
        extra = sorted(current_caps - gold_caps)
        if missing:
            output.append(_record("set", condition, "coverage", "medium", evidence=[f"Gold primary capability set contains: {', '.join(missing)}", "Capability overlap is a proxy for concern coverage; this does not prove a missed human concern."], repairability="local", recommended_repair="review_add_or_rewrite_criterion", confidence="medium"))
        if extra:
            output.append(_record("set", condition, "overreach", "low", evidence=[f"Generated primary capabilities not present in Gold: {', '.join(extra)}", "Gold absence is not proof of irrelevance; task support must be reviewed separately."], repairability="local", recommended_repair="review_task_support_before_drop", confidence="low"))
        comp = sum(str(r.get("atomicity")) == "compound" for r in current) / len(current) if current else 0.0
        gold_comp = sum(str(r.get("atomicity")) == "compound" for r in gold) / len(gold) if gold else 0.0
        if comp > gold_comp + 0.20:
            output.append(_record("set", condition, "granularity", "medium", evidence=[f"Compound rate generated={comp:.1%}, Gold={gold_comp:.1%}", "This is a distributional drift signal, not proof that every compound criterion is defective."], repairability="set_level", recommended_repair="review_parent_child_duplication_and_split_candidates", confidence="high"))
        multiplicity = Counter(_primary(r) for r in current)
        redundant = {k: v for k, v in multiplicity.items() if v > 1}
        if redundant:
            output.append(_record("set", condition, "granularity", "low", evidence=["Repeated primary capabilities: " + ", ".join(f"{k}×{v}" for k, v in sorted(redundant.items()))], repairability="set_level", recommended_repair="inspect_duplicate_or_decomposition_criteria", confidence="medium"))
        summary["set_level"].extend([x for x in output if x["condition"] == condition and x["level"] == "set"])

        for row in current:
            cid = str(row.get("criterion_id"))
            item = generated.get((condition, cid), {})
            text = criterion_text(row, item)
            lower = text.lower()
            subs = item.get("subrequirements") or row.get("subrequirements") or []
            if str(row.get("atomicity")) == "compound" or len(subs) > 1:
                if len(subs) >= 3:
                    output.append(_record("criterion", condition, "granularity", "medium", criterion_id=cid, evidence=[f"Criterion is compound with {len(subs)} subrequirements."], repairability="local", recommended_repair="split_or_make_aggregation_explicit", confidence="high"))
                else:
                    output.append(_record("criterion", condition, "granularity", "low", criterion_id=cid, evidence=["Criterion is classified as compound."], repairability="local", recommended_repair="inspect_atomicity_and_parent_child_overlap", confidence="medium"))
            if any(term in lower for term in NEGATIVE_MARKERS) and not (item.get("absence_semantics") or row.get("absence_semantics")):
                output.append(_record("criterion", condition, "boundary", "medium", criterion_id=cid, evidence=["Negative/absence wording has no recorded absence semantics."], repairability="local", recommended_repair="clarify_boundary", confidence="high"))
            if any(re.search(r"\\b" + re.escape(term) + r"\\b", lower) for term in VAGUE_TERMS) and not (item.get("boundary_notes") or item.get("anchors") or row.get("boundary_notes")):
                output.append(_record("criterion", condition, "boundary", "low", criterion_id=cid, evidence=["Vague evaluative term appears without recorded boundary or anchor."], repairability="local", recommended_repair="add_boundary_or_anchor", confidence="medium"))
            if str(row.get("grounding")) in {"human_general", "benchmark_specific"} and _primary(row) not in gold_caps:
                output.append(_record("criterion", condition, "overreach", "low", criterion_id=cid, evidence=[f"Grounding={row.get('grounding')} and primary capability={_primary(row)} is absent from Gold primary capability set.", "This is only a suspicion candidate; it requires task-support review."], repairability="local", recommended_repair="review_task_support_before_drop", confidence="low"))
            summary["criterion_level"].extend([x for x in output if x["condition"] == condition and x["criterion_id"] == cid and x["level"] == "criterion"])

        if stability:
            srows = _stability_records(stability, condition)
            for item in srows:
                if int(item.get("flip_count", 0) or 0) > 0:
                    output.append(_record("execution", condition, "measurement", "medium", criterion_id=str(item.get("criterion_id")), evidence=[f"5-repeat binary predictions={item.get('predictions')}", f"flip_count={item.get('flip_count')}", "A flip indicates execution instability, not necessarily a rubric defect."], repairability="review", recommended_repair="separate_call_level_failure_then_review_boundary", confidence="high"))
            data = ((stability.get("conditions") or {}).get(condition) or {})
            statuses = data.get("status_counts") or {}
            if statuses.get("incomplete_evidence") or statuses.get("judge_error"):
                output.append(_record("execution", condition, "measurement", "high", evidence=[f"Service/status issues: {statuses}", "Execution-level status failure must not be attributed to rubric wording without separate diagnosis."], repairability="evaluation_input", recommended_repair="separate_call_level_failure_from_rubric_instability", confidence="high"))
            summary["execution_level"].extend([x for x in output if x["condition"] == condition and x["level"] == "execution"])

    return {"schema_version": "agenteval.rubric_defect_attribution.v1", "gold_condition": gold_condition, "taxonomy": {"set_level": ["coverage", "overreach", "granularity"], "criterion_level": ["coverage", "overreach", "granularity", "boundary", "evidence"], "execution_level": ["measurement", "evidence"]}, "interpretation": "All records are defect candidates for human review. They are not automatic error labels.", "counts": {level: len(items) for level, items in summary.items()}, "findings": output}


def render_report(result: Mapping[str, Any]) -> str:
    findings = list(result.get("findings") or [])
    lines = ["# Rubric Defect Attribution", "", "所有 findings 都是人工复核候选，不是自动错误判定。特别是 Gold 未出现、分布异常、Judge flip 都不能单独证明 rubric 有缺陷。", "", "## Findings by level", "", "| Level | Count |", "|---|---:|"]
    for level, count in (result.get("counts") or {}).items():
        lines.append(f"| {level} | {count} |")
    lines += ["", "## Findings", "", "| Level | Condition | Defect | Severity | Criterion | Recommended repair | Evidence |", "|---|---|---|---|---|---|---|"]
    for x in findings:
        evidence = " / ".join(str(e).replace("|", "/") for e in x.get("evidence", []))[:220]
        lines.append(f"| {x.get('level')} | {x.get('condition')} | {x.get('defect_type')} | {x.get('severity')} | {x.get('criterion_id') or '-'} | {x.get('recommended_repair')} | {evidence} |")
    lines += ["", "## Repair action mapping", "", "| Defect | Default action |", "|---|---|", "| coverage | ADD or rewrite criterion after checking semantic alignment |", "| overreach | DROP only after task/benchmark support review |", "| granularity | SPLIT, merge, or remove parent-child duplication |", "| boundary | REWRITE boundary/anchor/absence semantics |", "| evidence | Fix evidence source/input, not automatically the rubric |", "| measurement | Separate call-level/evidence failure before rubric repair |", "", "## Boundary", "", "- No discrimination defect is inferred from this run-before-execution audit.", "- Applicability is not used as an active axis.", "- Generated criteria missing from Gold are not automatically extras or errors.", ""]
    return "\n".join(lines)


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
