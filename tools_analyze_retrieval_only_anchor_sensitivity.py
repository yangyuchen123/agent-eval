"""Analyze whether anchor representation changes autonomous retrieval policy."""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "run/meta_eval/retrieval-only-anchor-sensitivity-v1"
GOLD_DIR = ROOT / "run/meta_eval/failure-handling-blind-v1/gold"
CELLS = ["A_5_qualitative", "B_5_continuum", "C_6_qualitative", "D_6_continuum"]
CASE_IDS = [
    "att_fa8655f8ce1d", "att_8ca4f9ec3ba9", "att_9c539666b31d",
    "att_a1bb35bb6955", "att_07d7cc78f5b0",
]


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def trajectory_metrics(row: dict[str, Any], records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    actions = row.get("tool_trajectory") or []
    counts = Counter(x.get("operation") for x in actions)
    exposed = {str(i) for action in actions for i in action.get("result_ids") or []}
    cited = set(row.get("evidence_refs") or [])
    navigation = counts["call_context"] + counts["related"]
    if not actions:
        depth = 0
    elif set(counts) <= {"search"}:
        depth = 1
    elif navigation == 0:
        depth = 2
    elif navigation == 1:
        depth = 3
    else:
        depth = 4
    search_signatures = {
        json.dumps(x.get("parameters") or {}, sort_keys=True, ensure_ascii=False)
        for x in actions if x.get("operation") == "search"
    }
    exposed_records = [records[x] for x in exposed if x in records]
    agent_ids = {
        str(value) for record in exposed_records
        for value in (record.get("agent_id"), record.get("actor_agent_id"), record.get("target_agent_id"))
        if value
    }
    tool_call_ids = {str(record["tool_call_id"]) for record in exposed_records if record.get("tool_call_id")}
    return {
        "tool_call_count": len(actions),
        "search_count": counts["search"],
        "get_evidence_count": counts["get"],
        "get_call_context_count": counts["call_context"],
        "get_related_evidence_count": counts["related"],
        "investigation_depth": depth,
        "unique_search_branches": len(search_signatures),
        "exposed_evidence_ids": sorted(exposed),
        "cited_evidence_ids": sorted(cited),
        "unique_exposed_evidence_ids": len(exposed),
        "unique_cited_evidence_ids": len(cited),
        "unique_agent_ids": len(agent_ids),
        "unique_tool_call_ids": len(tool_call_ids),
        "last_tool_operation": actions[-1].get("operation") if actions else None,
        "last_tool_result_count": len(actions[-1].get("result_ids") or []) if actions else 0,
    }


def mean_or_none(values: list[float | int | None]) -> float | None:
    clean = [float(x) for x in values if x is not None]
    return statistics.mean(clean) if clean else None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    numeric = [
        "tool_call_count", "search_count", "get_evidence_count", "get_call_context_count",
        "get_related_evidence_count", "investigation_depth", "unique_search_branches",
        "unique_exposed_evidence_ids", "unique_cited_evidence_ids", "unique_agent_ids",
        "unique_tool_call_ids", "required_exposure_recall", "required_citation_recall",
        "gold_listed_citation_ratio",
    ]
    result = {key: mean_or_none([x.get(key) for x in rows]) for key in numeric}
    result.update({
        "observations": len(rows),
        "depth_distribution": dict(sorted(Counter(str(x["investigation_depth"]) for x in rows).items())),
        "last_tool_distribution": dict(sorted(Counter(str(x["last_tool_operation"]) for x in rows).items())),
        "provider_cost": sum(float((x.get("token_usage") or {}).get("cost") or 0) for x in rows),
        "mean_latency_ms": statistics.mean(float(x["latency_ms"]) for x in rows),
        "mean_input_tokens": statistics.mean(int((x.get("token_usage") or {}).get("input_tokens") or 0) for x in rows),
    })
    return result


def main() -> None:
    rows = [json.loads(x) for x in (OUT / "investigations.jsonl").read_text().splitlines() if x.strip()]
    snapshots = {case_id: json.loads((OUT / "snapshots" / f"{case_id}.json").read_text()) for case_id in CASE_IDS}
    gold = {case_id: json.loads((GOLD_DIR / f"{case_id}.json").read_text()) for case_id in CASE_IDS}
    enriched = []
    for row in rows:
        case_id = row["case_id"]
        records = {x["evidence_id"]: x for x in snapshots[case_id]["records"]}
        metrics = trajectory_metrics(row, records)
        required = set(gold[case_id].get("required_evidence_refs") or [])
        listed = required | set(gold[case_id].get("positive_evidence_refs") or []) | set(gold[case_id].get("negative_evidence_refs") or [])
        exposed = set(metrics["exposed_evidence_ids"])
        cited = set(metrics["cited_evidence_ids"])
        metrics["required_exposure_recall"] = len(required & exposed) / len(required) if required else None
        metrics["required_citation_recall"] = len(required & cited) / len(required) if required else None
        # Gold refs are known relevant but not exhaustive, so this is only a precision proxy.
        metrics["gold_listed_citation_ratio"] = len(cited & listed) / len(cited) if cited and listed else None
        enriched.append({**row, **metrics})

    by_cell = {cell: [x for x in enriched if x["condition"] == cell] for cell in CELLS}
    for cell, items in by_cell.items():
        if len(items) != 15:
            raise SystemExit(f"{cell}: expected 15 rows, found {len(items)}")
    cells = {cell: summarize(items) for cell, items in by_cell.items()}

    per_case = {}
    for case_id in CASE_IDS:
        per_case[case_id] = {}
        for cell in CELLS:
            items = sorted((x for x in by_cell[cell] if x["case_id"] == case_id), key=lambda x: x["repeat"])
            exposed_sets = [set(x["exposed_evidence_ids"]) for x in items]
            cited_sets = [set(x["cited_evidence_ids"]) for x in items]
            pairs = [(i, j) for i in range(len(items)) for j in range(i + 1, len(items))]
            per_case[case_id][cell] = {
                **summarize(items),
                "required_refs": gold[case_id].get("required_evidence_refs") or [],
                "mean_within_cell_exposed_jaccard": statistics.mean(jaccard(exposed_sets[i], exposed_sets[j]) for i, j in pairs),
                "mean_within_cell_cited_jaccard": statistics.mean(jaccard(cited_sets[i], cited_sets[j]) for i, j in pairs),
                "runs": [{
                    "repeat": x["repeat"], "depth": x["investigation_depth"],
                    "tool_calls": x["tool_call_count"], "required_exposure_recall": x["required_exposure_recall"],
                    "required_citation_recall": x["required_citation_recall"],
                    "exposed": x["exposed_evidence_ids"], "cited": x["cited_evidence_ids"],
                    "stop_reason": x["stop_reason"],
                } for x in items],
            }

    within_cell_stability = {}
    for cell in CELLS:
        within_cell_stability[cell] = {
            "mean_exposed_jaccard": statistics.mean(
                per_case[case_id][cell]["mean_within_cell_exposed_jaccard"] for case_id in CASE_IDS
            ),
            "mean_cited_jaccard": statistics.mean(
                per_case[case_id][cell]["mean_within_cell_cited_jaccard"] for case_id in CASE_IDS
            ),
        }

    paired = {}
    keyed = {cell: {(x["case_id"], int(x["repeat"])): x for x in items} for cell, items in by_cell.items()}
    for left, right in (("A_5_qualitative", "B_5_continuum"), ("C_6_qualitative", "D_6_continuum"),
                        ("A_5_qualitative", "C_6_qualitative"), ("B_5_continuum", "D_6_continuum")):
        comparisons = []
        for key in sorted(keyed[left]):
            l, r = keyed[left][key], keyed[right][key]
            comparisons.append({
                "case_id": key[0], "repeat": key[1],
                "exposed_jaccard": jaccard(set(l["exposed_evidence_ids"]), set(r["exposed_evidence_ids"])),
                "cited_jaccard": jaccard(set(l["cited_evidence_ids"]), set(r["cited_evidence_ids"])),
                "tool_call_delta": r["tool_call_count"] - l["tool_call_count"],
                "depth_delta": r["investigation_depth"] - l["investigation_depth"],
                "required_exposure_recall_delta": (
                    r["required_exposure_recall"] - l["required_exposure_recall"]
                    if r["required_exposure_recall"] is not None else None
                ),
                "required_citation_recall_delta": (
                    r["required_citation_recall"] - l["required_citation_recall"]
                    if r["required_citation_recall"] is not None else None
                ),
            })
        mean_cross_exposed = statistics.mean(x["exposed_jaccard"] for x in comparisons)
        mean_cross_cited = statistics.mean(x["cited_jaccard"] for x in comparisons)
        pooled_within_exposed = statistics.mean([
            within_cell_stability[left]["mean_exposed_jaccard"],
            within_cell_stability[right]["mean_exposed_jaccard"],
        ])
        pooled_within_cited = statistics.mean([
            within_cell_stability[left]["mean_cited_jaccard"],
            within_cell_stability[right]["mean_cited_jaccard"],
        ])
        paired[f"{left}_vs_{right}"] = {
            "mean_exposed_jaccard": mean_cross_exposed,
            "mean_cited_jaccard": mean_cross_cited,
            "pooled_within_cell_exposed_jaccard": pooled_within_exposed,
            "pooled_within_cell_cited_jaccard": pooled_within_cited,
            "cross_minus_within_exposed_jaccard": mean_cross_exposed - pooled_within_exposed,
            "cross_minus_within_cited_jaccard": mean_cross_cited - pooled_within_cited,
            "mean_tool_call_delta": statistics.mean(x["tool_call_delta"] for x in comparisons),
            "mean_depth_delta": statistics.mean(x["depth_delta"] for x in comparisons),
            "mean_required_exposure_recall_delta": mean_or_none([x["required_exposure_recall_delta"] for x in comparisons]),
            "mean_required_citation_recall_delta": mean_or_none([x["required_citation_recall_delta"] for x in comparisons]),
            "rows": comparisons,
        }

    result = {
        "schema_version": "agenteval.retrieval_only_anchor_sensitivity_analysis.v1",
        "cells": cells,
        "per_case": per_case,
        "within_cell_stability": within_cell_stability,
        "paired_comparisons": paired,
        "controls": {
            "observations": len(enriched),
            "same_record_digest_by_case": all(len({x["record_digest"] for x in enriched if x["case_id"] == c}) == 1 for c in CASE_IDS),
            "no_scoring_fields": all(not ({"score", "status", "confidence"} & set(x)) for x in rows),
            "models": sorted({x["model"] for x in rows}),
        },
        "metric_availability": {
            "irrelevant_evidence_rate": "unavailable: Gold evidence refs are relevant anchors but not exhaustive labels for every catalog record",
            "gold_listed_citation_ratio": "available only as a non-exhaustive precision proxy",
        },
    }
    (OUT / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "output": str(OUT / "analysis.json"), "cells": cells,
        "paired": {k: {x: v[x] for x in v if x != "rows"} for k, v in paired.items()},
        "controls": result["controls"], "metric_availability": result["metric_availability"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
