"""Parse and normalize official GDPval rubric judge JSON.

Shared by the Blade env scorer and the Pi workbook judge so both produce the
same binary review object.  Partial credit is rejected.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence


def _hamming(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right))
    return sum(a != b for a, b in zip(left, right))


def repair_rubric_ids(result: dict[str, Any], rubric: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Map a single near-miss UUID onto the missing official id.

    Pi sometimes transposes one hex character in a 36-char rubric_item_id.
    Only repair when exactly one official id is missing and exactly one extra
    id is a unique nearest neighbour (Hamming ≤ 2).  Record repairs; do not
    silently drop items.
    """
    scores = result.get("rubric_scores")
    if not isinstance(scores, list):
        return dict(result)
    official = [str(item["rubric_item_id"]) for item in rubric]
    official_set = set(official)
    got = [str(item.get("rubric_item_id") or "") for item in scores if isinstance(item, dict)]
    missing = [item_id for item_id in official if item_id not in set(got)]
    extra = [item_id for item_id in got if item_id and item_id not in official_set]
    repairs: list[dict[str, str]] = []
    remaining_missing = list(missing)
    for extra_id in extra:
        distances = sorted((_hamming(extra_id, item_id), item_id) for item_id in remaining_missing)
        if not distances:
            break
        best, match = distances[0]
        second = distances[1][0] if len(distances) > 1 else None
        if best == 0 or best > 2:
            continue
        if second is not None and second == best:
            continue
        repairs.append({"from": extra_id, "to": match, "hamming": str(best), "method": "hamming"})
        remaining_missing.remove(match)
        for item in scores:
            if isinstance(item, dict) and str(item.get("rubric_item_id") or "") == extra_id:
                item["rubric_item_id"] = match
                item["id_repaired_from"] = extra_id
                break
    if not remaining_missing and extra and len(scores) == len(official):
        pass
    elif remaining_missing and extra and len(scores) == len(official) == 56:
        # Positional fallback: exactly one extra id sitting in the missing
        # item's official slot, prefix still matches the official family.
        if len(remaining_missing) == 1 and len(extra) == 1:
            miss = remaining_missing[0]
            extra_id = extra[0]
            try:
                idx = next(i for i, item in enumerate(scores) if isinstance(item, dict) and str(item.get("rubric_item_id") or "") == extra_id)
            except StopIteration:
                idx = -1
            official_idx = official.index(miss)
            prefix_ok = extra_id.split("-")[0] == miss.split("-")[0]
            if idx == official_idx and prefix_ok:
                for item in scores:
                    if isinstance(item, dict) and str(item.get("rubric_item_id") or "") == extra_id:
                        item["rubric_item_id"] = miss
                        item["id_repaired_from"] = extra_id
                        break
                repairs.append({"from": extra_id, "to": miss, "hamming": str(_hamming(extra_id, miss)), "method": "positional_prefix"})
                remaining_missing = []
    out = dict(result)
    if repairs:
        out["id_repairs"] = repairs
    return out


def parse_model_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and isinstance(parsed.get("rubric_scores"), list):
            return parsed
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("rubric_scores"), list):
            return parsed
    raise ValueError("no complete judge JSON object with rubric_scores found")


def normalize_official_result(result: Mapping[str, Any], rubric: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scores = result.get("rubric_scores")
    if not isinstance(scores, list):
        raise ValueError("rubric_scores must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    for item in scores:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("rubric_item_id") or "")
        if not item_id:
            continue
        if item_id in by_id:
            raise ValueError(f"duplicate rubric item: {item_id}")
        by_id[item_id] = item

    normalized: list[dict[str, Any]] = []
    for expected in rubric:
        item_id = str(expected["rubric_item_id"])
        item = by_id.get(item_id)
        if item is None:
            raise ValueError(f"missing rubric item: {item_id}")
        max_points = int(expected.get("score") if expected.get("score") is not None else expected.get("max_points") or 0)
        passed = item.get("passed")
        if isinstance(passed, bool):
            awarded = max_points if passed else 0
        else:
            try:
                awarded = int(item.get("awarded"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"missing binary passed decision for {item_id}") from exc
            if awarded not in {0, max_points}:
                raise ValueError(f"non-binary awarded points for {item_id}: {awarded}/{max_points}")
            passed = awarded == max_points
        refs = item.get("evidence_refs") or []
        if not isinstance(refs, list):
            refs = []
        normalized.append(
            {
                "rubric_item_id": item_id,
                "passed": bool(passed),
                "awarded": awarded,
                "max_points": max_points,
                "reason": str(item.get("reason") or ""),
                "evidence_refs": [str(x) for x in refs],
            }
        )

    awarded_total = sum(item["awarded"] for item in normalized)
    max_total = sum(item["max_points"] for item in normalized)
    overall = result.get("overall") if isinstance(result.get("overall"), dict) else {}
    confidence = overall.get("confidence")
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    return {
        "schema_version": "gdpval_rubric_judge.v1",
        "rubric_scores": normalized,
        "overall": {
            "awarded_points": awarded_total,
            "max_points": max_total,
            "confidence": confidence,
            "summary": str(overall.get("summary") or ""),
        },
        "unverified_items": [str(x) for x in (result.get("unverified_items") or []) if x],
        "human_attention_points": [str(x) for x in (result.get("human_attention_points") or []) if x],
    }


def score_100(result: Mapping[str, Any]) -> int:
    overall = result["overall"]
    maximum = int(overall["max_points"])
    return round(100 * int(overall["awarded_points"]) / maximum) if maximum else 0
