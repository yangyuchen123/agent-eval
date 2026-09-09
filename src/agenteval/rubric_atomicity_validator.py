"""Independent, conservative validator for RubricRefiner proposals."""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

SCHEMA = "agenteval.rubric_atomicity_validator.v1"


def _words(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z][A-Za-z0-9_-]*|[\u4e00-\u9fff]+", text.lower()))


def validate_atomicity(original: Mapping[str, Any], proposal: Mapping[str, Any], task_context: str = "") -> dict[str, Any]:
    """Perform conservative structural checks.

    This is intentionally not a satisfaction judge. It can reject malformed or
    obviously redundant splits, but uncertain semantic cases remain review.
    """
    action = str(proposal.get("action", "")).upper()
    original_text = str(original.get("text") or original.get("criterion") or "").strip()
    replacements = proposal.get("replacement_criteria") or []
    issues: list[dict[str, str]] = []
    if action == "KEEP":
        accepted = not replacements and bool(original_text)
        if replacements:
            issues.append({"type": "keep_has_replacements", "message": "KEEP must have an empty replacement_criteria list."})
        return _result(accepted, coverage_preserved=accepted, all_atomic=accepted, semantic_expansion=False, over_split=False, redundancy_created=False, issues=issues)
    if action != "SPLIT":
        return _result(False, False, False, False, False, False, [{"type": "invalid_action", "message": "Action must be KEEP or SPLIT."}])
    if not isinstance(replacements, list) or len(replacements) < 2:
        issues.append({"type": "too_few_replacements", "message": "SPLIT requires at least two replacement criteria."})
    texts = [str(x.get("text") or "").strip() for x in replacements if isinstance(x, Mapping)]
    if any(not text for text in texts):
        issues.append({"type": "empty_replacement", "message": "Every replacement must contain text."})
    ids = [str(x.get("criterion_id") or "") for x in replacements if isinstance(x, Mapping)]
    if len(ids) != len(set(ids)):
        issues.append({"type": "duplicate_replacement_id", "message": "Replacement criterion ids must be unique."})
    # Explicit metadata in a replacement would violate the narrow patch API.
    forbidden = set().union(*(set(x) - {"criterion_id", "text"} for x in replacements if isinstance(x, Mapping)))
    if forbidden:
        issues.append({"type": "replacement_contains_metadata", "message": f"Replacement contains forbidden metadata: {sorted(forbidden)}"})
    # Heuristic only: a replacement cannot introduce a large vocabulary absent
    # from the source unless it is a function word. Final semantic coverage is
    # deliberately left to independent review/model validation.
    source_words = _words(original_text)
    stop = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is", "are", "be", "must", "should", "要", "并", "且", "的", "应"}
    expansion = []
    for text in texts:
        novel = sorted(_words(text) - source_words - stop)
        if novel:
            expansion.append((text, novel))
    semantic_expansion = False
    # Novel words alone are not proof of expansion: splitting often requires
    # grammatical rephrasing. Flag only very large novel content as review.
    if expansion and sum(len(words) for _, words in expansion) > max(8, len(source_words)):
        semantic_expansion = True
        issues.append({"type": "possible_semantic_expansion", "message": "Replacement vocabulary substantially exceeds the original; independent semantic review required."})
    # Only flag near-identical replacements. Shared template words (for
    # example, "The workbook contains...") are expected after a valid split
    # and are not redundancy by themselves.
    redundancy = False
    for i, left in enumerate(texts):
        for right in texts[i + 1:]:
            a, b = _words(left), _words(right)
            union = len(a | b)
            jaccard = len(a & b) / union if union else 0.0
            if a and b and jaccard >= 0.92 and abs(len(a) - len(b)) <= 4:
                redundancy = True
                issues.append({"type": "obvious_redundancy", "message": "Two replacements are near-identical."})
    # Conjunctions are not sufficient evidence of a compound replacement:
    # they often occur inside one proposition (e.g. "dates and amounts").
    # Leave semantic independence to the independent validator/model.
    all_atomic = not any(";" in text or "\n" in text for text in texts)
    coverage_preserved = bool(texts) and not semantic_expansion
    if not coverage_preserved:
        issues.append({"type": "coverage_not_established", "message": "Coverage cannot be established conservatively from the proposal."})
    accepted = bool(texts) and not issues
    return _result(accepted, coverage_preserved, all_atomic, semantic_expansion, len(texts) > 4, redundancy, issues)


def _result(accept: bool, coverage_preserved: bool, all_atomic: bool, semantic_expansion: bool, over_split: bool, redundancy_created: bool, issues: list[dict[str, str]]) -> dict[str, Any]:
    return {"schema_version": SCHEMA, "coverage_preserved": bool(coverage_preserved), "all_atomic": bool(all_atomic), "semantic_expansion": bool(semantic_expansion), "over_split": bool(over_split), "redundancy_created": bool(redundancy_created), "accept": bool(accept), "issues": issues}


def atomicity_validator_prompt(original: Mapping[str, Any], replacements: Sequence[Mapping[str, Any]], task_context: str = "") -> list[dict[str, str]]:
    """Build an independent semantic validation prompt.

    The deterministic validator remains the first gate; this prompt is for a
    separately configured validator when semantic review is needed.
    """
    import json
    payload = {"task_context": task_context, "original_criterion": dict(original), "replacement_criteria": [dict(x) for x in replacements]}
    system = """You are AtomicityValidator, independent of RubricRefiner. Validate only a KEEP/SPLIT proposal; do not judge satisfaction, Gold, or Judge predictions. Answer five questions: (1) coverage_preserved, (2) all_atomic, (3) semantic_expansion, (4) over_split, (5) redundancy_created. Accept only when coverage is preserved, every replacement is a minimum independently judgeable proposition, no requirement was added, the split is not excessive, and replacements are not redundant. For KEEP, validate that the original is already one minimum independently judgeable proposition. Return only JSON."""
    user = "Input:\n" + json.dumps(payload, ensure_ascii=False, indent=2) + """

Return exactly: {"coverage_preserved":true,"all_atomic":true,"semantic_expansion":false,"over_split":false,"redundancy_created":false,"accept":true,"issues":[]}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
