"""Rubric-property classification and descriptive statistics.

This module describes rubric criteria; it does not judge criterion satisfaction and
must not consume Gold labels, Judge predictions, or accuracy.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .capability_alignment import GDPVAL_CAPABILITIES, GDPVAL_CAPABILITY_DEFINITIONS

GROUNDING = {"human_general", "benchmark_specific", "task_specific"}
SCOPES = {"process", "outcome", "policy", "artifact"}
APPLICABILITY = {"always", "conditional", "task_specific"}
EVIDENCE_SOURCES = {"trajectory", "artifact", "state", "mixed"}
ATOMICITY = {"atomic", "compound"}
HARDNESS = {"hard", "soft"}
JUDGMENT_TYPES = {"objective", "subjective"}


def _dist(rows: list[Mapping[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(r.get(key, "unknown")) for r in rows).items()))


def validate_record(row: Mapping[str, Any]) -> list[str]:
    """Return schema errors for one flattened classification row."""
    errors: list[str] = []
    required = ("criterion_id", "condition", "grounding", "scope", "applicability", "evidence_source", "atomicity", "hardness", "judgment_type", "capability")
    for key in required:
        if key not in row:
            errors.append(f"missing:{key}")
    if str(row.get("grounding")) not in GROUNDING:
        errors.append(f"invalid:grounding={row.get('grounding')}")
    if str(row.get("scope")) not in SCOPES:
        errors.append(f"invalid:scope={row.get('scope')}")
    if str(row.get("applicability")) not in APPLICABILITY:
        errors.append(f"invalid:applicability={row.get('applicability')}")
    if str(row.get("evidence_source")) not in EVIDENCE_SOURCES:
        errors.append(f"invalid:evidence_source={row.get('evidence_source')}")
    if str(row.get("atomicity")) not in ATOMICITY:
        errors.append(f"invalid:atomicity={row.get('atomicity')}")
    if str(row.get("hardness")) not in HARDNESS:
        errors.append(f"invalid:hardness={row.get('hardness')}")
    if str(row.get("judgment_type")) not in JUDGMENT_TYPES:
        errors.append(f"invalid:judgment_type={row.get('judgment_type')}")
    cap = row.get("capability")
    if not isinstance(cap, Mapping) or not cap.get("primary"):
        errors.append("invalid:capability.primary")
    if str(row.get("atomicity")) == "compound":
        subs = row.get("subrequirements", [])
        if not isinstance(subs, list) or not subs:
            errors.append("compound_without_subrequirements")
        if not row.get("aggregation_rule"):
            errors.append("compound_without_aggregation_rule")
    return errors


def compute_metrics(rows: Iterable[Mapping[str, Any]], *, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    rows = [dict(r) for r in rows]
    conditions = sorted({str(r.get("condition", "unknown")) for r in rows})
    result: dict[str, Any] = {
        "schema_version": "agenteval.rubric_classification_metrics.v1",
        "row_count": len(rows),
        "conditions": {},
        "validation": {"invalid_row_count": 0, "errors": []},
    }
    for row in rows:
        errors = validate_record(row)
        if errors:
            result["validation"]["invalid_row_count"] += 1
            result["validation"]["errors"].append({"condition": row.get("condition"), "criterion_id": row.get("criterion_id"), "errors": errors})
    for condition in conditions:
        part = [r for r in rows if str(r.get("condition")) == condition]
        n = len(part) or 1
        cross = Counter("|".join(str(partrow.get(k, "unknown")) for k in ("grounding", "scope", "applicability", "evidence_source", "atomicity", "hardness", "judgment_type")) for partrow in part)
        caps = Counter(str((r.get("capability") or {}).get("primary", "unknown")) for r in part)
        result["conditions"][condition] = {
            "criterion_count": len(part),
            "grounding": _dist(part, "grounding"),
            "scope": _dist(part, "scope"),
            "applicability": _dist(part, "applicability"),
            "evidence_source": _dist(part, "evidence_source"),
            "atomicity": _dist(part, "atomicity"),
            "hardness": _dist(part, "hardness"),
            "judgment_type": _dist(part, "judgment_type"),
            "capability": dict(sorted(caps.items())),
            "cross_distribution": dict(sorted(cross.items())),
            "rates": {
                "human_general": sum(r.get("grounding") == "human_general" for r in part) / n,
                "benchmark_specific": sum(r.get("grounding") == "benchmark_specific" for r in part) / n,
                "task_specific_grounding": sum(r.get("grounding") == "task_specific" for r in part) / n,
                "process": sum(r.get("scope") == "process" for r in part) / n,
                "outcome": sum(r.get("scope") == "outcome" for r in part) / n,
                "policy": sum(r.get("scope") == "policy" for r in part) / n,
                "artifact": sum(r.get("scope") == "artifact" for r in part) / n,
                "always": sum(r.get("applicability") == "always" for r in part) / n,
                "conditional": sum(r.get("applicability") == "conditional" for r in part) / n,
                "task_specific_applicability": sum(r.get("applicability") == "task_specific" for r in part) / n,
                "trajectory": sum(r.get("evidence_source") == "trajectory" for r in part) / n,
                "artifact_evidence": sum(r.get("evidence_source") == "artifact" for r in part) / n,
                "state": sum(r.get("evidence_source") == "state" for r in part) / n,
                "mixed": sum(r.get("evidence_source") == "mixed" for r in part) / n,
                "atomic": sum(r.get("atomicity") == "atomic" for r in part) / n,
                "compound": sum(r.get("atomicity") == "compound" for r in part) / n,
                "hard": sum(r.get("hardness") == "hard" for r in part) / n,
                "soft": sum(r.get("hardness") == "soft" for r in part) / n,
                "objective": sum(r.get("judgment_type") == "objective" for r in part) / n,
                "subjective": sum(r.get("judgment_type") == "subjective" for r in part) / n,
            },
        }
    if metadata:
        result["metadata"] = dict(metadata)
    return result


def write_jsonl(rows: Iterable[Mapping[str, Any]], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(dict(r), ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def root_id(criterion_id: str) -> str:
    return str(criterion_id).split(".", 1)[0]


def build_lineage(
    *,
    condition: str,
    old_criteria: Sequence[Mapping[str, Any]],
    new_criteria: Sequence[Mapping[str, Any]],
    dropped: Sequence[Mapping[str, Any]] | None = None,
    tree: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic old-to-new mapping. Split/kept/dropped come from IDs, not LLM."""
    old_ids = [str(x.get("criterion_id") or x.get("rubric_id")) for x in old_criteria]
    new_ids = [str(x.get("criterion_id") or x.get("rubric_id")) for x in new_criteria]
    dropped_ids = {str(x.get("rubric_id") or x.get("criterion_id")) for x in (dropped or [])}
    children: dict[str, list[str]] = {}
    for nid in new_ids:
        children.setdefault(root_id(nid), []).append(nid)
    kept, split, missing = [], [], []
    for oid in old_ids:
        kids = children.get(oid, [])
        exact = oid in kids
        descendants = [x for x in kids if x != oid]
        if descendants:
            split.append({"old_id": oid, "new_ids": sorted(kids), "action": "split"})
        elif exact:
            kept.append({"old_id": oid, "new_ids": [oid], "action": "kept"})
        else:
            missing.append({"old_id": oid, "new_ids": [], "action": "dropped_or_absent", "in_dropped_list": oid in dropped_ids or any(x.startswith(oid + ".") for x in dropped_ids)})
    return {
        "schema_version": "agenteval.rrd_lineage.v1",
        "condition": condition,
        "old_count": len(old_ids),
        "new_count": len(new_ids),
        "kept": kept,
        "split": split,
        "dropped_or_absent": missing,
        "dropped_records": [dict(x) for x in (dropped or [])],
        "counts": {"kept": len(kept), "split": len(split), "dropped_or_absent": len(missing), "new_children": sum(len(x["new_ids"]) for x in split)},
        "tree_keys": sorted((tree or {}).keys()),
    }


def all_axes_prompt(task: str, criteria: Sequence[Mapping[str, Any]], *, condition: str) -> list[dict[str, str]]:
    payload = {
        "task": task,
        "condition": condition,
        "capability_definitions": GDPVAL_CAPABILITY_DEFINITIONS,
        "allowed_capabilities": GDPVAL_CAPABILITIES,
        "allowed_values": {
            "grounding": sorted(GROUNDING),
            "scope": sorted(SCOPES),
            "applicability": sorted(APPLICABILITY),
            "evidence_source": sorted(EVIDENCE_SOURCES),
            "atomicity": sorted(ATOMICITY),
            "hardness": sorted(HARDNESS),
            "judgment_type": sorted(JUDGMENT_TYPES),
        },
        "criteria": [{
            "criterion_id": str(x.get("criterion_id") or x.get("rubric_id")),
            "criterion": str(x.get("criterion") or x.get("text") or ""),
            "source_criterion_id": x.get("source_criterion_id"),
        } for x in criteria],
    }
    system = """You are a rubric-property annotator. Classify EACH criterion independently on ALL active axes.

Do not judge whether a criterion is satisfied. Do not output Gold labels, scores, accuracy, or Judge predictions.
GDPval is artifact-centric: evidence_source follows the criterion's required evidence, not whether a runtrace exists.

AXES
- grounding: human_general / benchmark_specific / task_specific
- scope: process=how the agent acts; outcome=final task result; policy=rule/constraint; artifact=deliverable properties
- applicability: always / conditional / task_specific
- evidence_source: trajectory / artifact / state / mixed
- atomicity: atomic=one independent yes/no; compound=multiple independent subrequirements
- hardness: hard=sharp fail boundary; soft=graded or stylistic
- judgment_type: objective / subjective
- capability.primary: exactly one ID from allowed_capabilities; secondary at most two independent extras

For compound criteria provide subrequirements and aggregation_rule ALL|ANY. For atomic use empty subrequirements and aggregation_rule not_applicable.
Use only allowed values. Return JSON only."""
    user = "Input:\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n\nReturn exactly: {\"results\":[{\"criterion_id\":\"gen_001\",\"grounding\":\"task_specific\",\"grounding_secondary\":[],\"scope\":\"artifact\",\"scope_secondary\":[],\"applicability\":\"always\",\"evidence_source\":\"artifact\",\"atomicity\":\"atomic\",\"subrequirements\":[],\"aggregation_rule\":\"not_applicable\",\"hardness\":\"hard\",\"judgment_type\":\"objective\",\"capability\":{\"primary\":\"spreadsheet_structure\",\"secondary\":[]},\"confidence\":\"high\",\"basis\":\"...\"}]}. Include every input criterion_id exactly once."
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def flatten_classification_item(item: Mapping[str, Any], *, condition: str, criterion_text: str = "", source_criterion_id: str | None = None) -> dict[str, Any]:
    cap = item.get("capability") if isinstance(item.get("capability"), Mapping) else {}
    atomicity = str(item.get("atomicity") or "")
    subs = item.get("subrequirements") if isinstance(item.get("subrequirements"), list) else []
    aggregation = item.get("aggregation_rule") or ("not_applicable" if atomicity == "atomic" else "ALL")
    return {
        "condition": condition,
        "criterion_id": str(item.get("criterion_id") or ""),
        "source_criterion_id": source_criterion_id,
        "criterion": criterion_text or str(item.get("criterion") or ""),
        "grounding": str(item.get("grounding") or ""),
        "grounding_secondary": list(item.get("grounding_secondary") or []),
        "scope": str(item.get("scope") or ""),
        "scope_secondary": list(item.get("scope_secondary") or []),
        "applicability": str(item.get("applicability") or ""),
        "evidence_source": str(item.get("evidence_source") or ""),
        "atomicity": atomicity,
        "subrequirements": subs,
        "aggregation_rule": aggregation,
        "hardness": str(item.get("hardness") or ""),
        "judgment_type": str(item.get("judgment_type") or ""),
        "capability": {"primary": cap.get("primary") or cap.get("primary_capability"), "secondary": list(cap.get("secondary") or cap.get("secondary_capabilities") or [])},
        "confidence": str(item.get("confidence") or ""),
        "basis": str(item.get("basis") or ""),
        "classification_method": "analyst_llm",
        "status": "machine_proposed",
    }


def parse_classification_output(parsed: Any, criteria: Sequence[Mapping[str, Any]], *, condition: str) -> list[dict[str, Any]]:
    raw = parsed.get("results") if isinstance(parsed, dict) else None
    if not isinstance(raw, list):
        raise ValueError("classification output must contain results list")
    by_id = {str(x.get("criterion_id") or x.get("rubric_id")): x for x in criteria}
    out = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("criterion_id") or "")
        if cid not in by_id or cid in seen:
            continue
        src = by_id[cid]
        out.append(flatten_classification_item(
            item,
            condition=condition,
            criterion_text=str(src.get("criterion") or src.get("text") or ""),
            source_criterion_id=src.get("source_criterion_id"),
        ))
        seen.add(cid)
    missing = [cid for cid in by_id if cid not in seen]
    if missing:
        raise ValueError(f"classification missing criterion_ids: {missing}")
    return out


ACTIVE_COMPARE_AXES = ("grounding", "scope", "evidence_source", "atomicity", "hardness", "judgment_type", "capability")


def _axis_value(row: Mapping[str, Any], axis: str) -> str:
    value = row.get(axis)
    if axis == "capability":
        if isinstance(value, Mapping):
            value = value.get("primary") or value.get("primary_capability")
        elif not value:
            value = "unknown"
    return str(value or "unknown")


def lineage_axis_changes(old_rows: Sequence[Mapping[str, Any]], new_rows: Sequence[Mapping[str, Any]], lineage: Mapping[str, Any]) -> list[dict[str, Any]]:
    old_by = {str(x.get("criterion_id")): x for x in old_rows}
    new_by = {str(x.get("criterion_id")): x for x in new_rows}
    changes = []
    for group, action in (("kept", "kept"), ("split", "split"), ("dropped_or_absent", "dropped")):
        for item in lineage.get(group, []):
            oid = item["old_id"]
            old = old_by.get(oid, {})
            for nid in item.get("new_ids") or [None]:
                new = new_by.get(nid or "", {})
                axis_delta = {}
                for axis in ACTIVE_COMPARE_AXES:
                    before = _axis_value(old, axis)
                    after = _axis_value(new, axis) if new else None
                    if before != after:
                        axis_delta[axis] = {"old": before, "new": after}
                changes.append({
                    "action": action,
                    "old_id": oid,
                    "new_id": nid,
                    "old_text": old.get("criterion"),
                    "new_text": new.get("criterion"),
                    "axis_changes": axis_delta,
                    "changed_axis_count": len(axis_delta),
                })
    return changes
