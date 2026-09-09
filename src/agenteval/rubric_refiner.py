"""Minimal compound-rubric refinement role.

RubricRefiner only proposes KEEP or SPLIT for BugFind-selected criteria. It
never sees Gold/Judge outcomes and never remaps metadata or capabilities.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

SCHEMA = "agenteval.rubric_refiner.v1"


def _criterion_payload(criterion: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "criterion_id": criterion.get("criterion_id"),
        "text": criterion.get("text") or criterion.get("criterion") or "",
        "grounding": criterion.get("grounding"),
        "scope": criterion.get("scope"),
        "evidence_source": criterion.get("evidence_source"),
        "atomicity": criterion.get("atomicity"),
        "hardness": criterion.get("hardness"),
        "judgment_type": criterion.get("judgment_type"),
        "primary_capability": criterion.get("primary_capability") or (criterion.get("capability") or {}).get("primary"),
    }


def refiner_prompt(items: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Build one batch prompt for one or more BugFind candidates."""
    payload = [{
        "task_id": item.get("task_id"),
        "task_context": item.get("task_context", ""),
        "criterion": _criterion_payload(item.get("criterion") or item),
        "defect": {
            "type": "compound",
            "reason": (item.get("defect") or {}).get("reason", "") if isinstance(item.get("defect"), Mapping) else "",
            "evidence": (item.get("defect") or {}).get("evidence", []) if isinstance(item.get("defect"), Mapping) else [],
        },
    } for item in items]
    system = """You are RubricRefiner, downstream of BugFind.

Your only task is to make a MINIMAL atomicity proposal for each supplied
criterion. Return exactly one action: KEEP or SPLIT.

ROLE BOUNDARY (hard constraints)
- BugFind identifies candidates; it is not proof that a split is needed.
- Do not use or request Judge scores, Judge predictions, Gold labels, flip
  results, or A/B/C/D condition information. They are not provided.
- Do not regenerate a rubric set, DROP a criterion, or add an evaluation
  dimension.
- Preserve every requirement expressed by the original criterion.
- Do not change its source/grounding, hardness, judgment_type, or capability.
- If splitting would require capability remapping, set
  capability_reclassification_needed=true; do not remap it yourself.

ATOMICITY RULE
A criterion is atomic when it is the minimum independently judgeable
proposition. Split only when two or more requirements can independently be
true/false in a semantically reasonable case. Do not split nouns, locations,
qualifiers, or supporting detail that forms one proposition. For example,
"Prepaid Summary header includes the company name Aurisic" stays KEEP.

SPLIT RULES
- Every replacement must be independently answerable Yes/No.
- Preserve the original evaluation intent; no semantic expansion.
- Use the minimum number of replacement criteria.
- Replacement text may clarify grammar but must not add requirements.
- Keep the original criterion id as a prefix (for example R7.1, R7.2).

Return only JSON with key `results` and one result per input item."""
    user = "Input:\n" + json.dumps(payload, ensure_ascii=False, indent=2) + """

Return exactly:
{"results":[{"task_id":"...","action":"KEEP|SPLIT","original_criterion_id":"...","reason":"...","replacement_criteria":[{"criterion_id":"R7.1","text":"..."}],"capability_reclassification_needed":false}]}

For KEEP, replacement_criteria must be []. For SPLIT, provide at least two
replacement criteria and no metadata fields. Do not include Gold labels or
Judge-related fields."""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def normalize_result(result: Mapping[str, Any], original: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a model proposal without inventing metadata."""
    action = str(result.get("action", "")).upper()
    cid = str(original.get("criterion_id") or result.get("original_criterion_id") or "")
    replacements = result.get("replacement_criteria") or []
    normalized = {
        "schema_version": SCHEMA,
        "action": action if action in {"KEEP", "SPLIT"} else "INVALID",
        "original_criterion_id": cid,
        "reason": str(result.get("reason") or ""),
        "replacement_criteria": [],
        "capability_reclassification_needed": bool(result.get("capability_reclassification_needed", False)),
    }
    if isinstance(replacements, list):
        for index, replacement in enumerate(replacements, 1):
            if not isinstance(replacement, Mapping):
                continue
            rid = str(replacement.get("criterion_id") or f"{cid}.{index}")
            normalized["replacement_criteria"].append({"criterion_id": rid, "text": str(replacement.get("text") or replacement.get("criterion") or "")})
    return normalized


def inherit_metadata(original: Mapping[str, Any], replacement: Mapping[str, Any]) -> dict[str, Any]:
    """Attach unchanged metadata to a replacement criterion."""
    output = dict(replacement)
    for key in ("grounding", "grounding_secondary", "scope", "scope_secondary", "evidence_source", "hardness", "judgment_type", "capability", "primary_capability"):
        if key in original:
            output[key] = original[key]
    output["source_criterion_id"] = original.get("criterion_id")
    output["atomicity"] = "atomic"
    return output
