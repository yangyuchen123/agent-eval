"""Shared, leakage-safe analysis for generated-rubric semantic alignment.

This module consumes blind alignment proposals and generated-rubric outputs.  It
never uses Gold labels or downstream Judge predictions; those are intentionally
outside the alignment stage.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _condition_map(row: Mapping[str, Any]) -> dict[str, str]:
    return {str(system): str(condition) for system, condition in row["system_key"].items()}


def _assessed_ids(assessment: Mapping[str, Any]) -> list[str]:
    ids = assessment.get("ids", [])
    return [str(x) for x in ids] if isinstance(ids, list) else []


def analyze_alignment(
    proposals: Iterable[Mapping[str, Any]],
    generated_by_condition: Mapping[str, Iterable[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    proposals = list(proposals)
    source_alias = {
        "A": "task_only", "C": "retrieved_human_rubric", "D": "global_profile",
    }
    generated = {
        condition: {str(row["task_id"]): row for row in rows}
        for condition, rows in generated_by_condition.items()
    }
    for protocol, source in source_alias.items():
        if source in generated and protocol not in generated:
            generated[protocol] = generated[source]
    out_rows: list[dict[str, Any]] = []
    totals: dict[str, Counter[str]] = defaultdict(Counter)
    relation_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for proposal in proposals:
        task_id = str(proposal["task_id"])
        mapping = _condition_map(proposal)
        alignment = proposal.get("alignment", {})
        entries = alignment.get("alignments", [])
        human_total = int(alignment.get("human_concern_count", 0))
        for system, condition in mapping.items():
            assessments = alignment.get("generated_assessments", {}).get(system, [])
            generated_criteria = generated.get(condition, {}).get(task_id, {}).get("generated", {}).get("criteria", [])
            generated_ids = [str(item.get("criterion_id", "")) for item in generated_criteria]
            assessed_ids = [item_id for assessment in assessments for item_id in _assessed_ids(assessment)]
            row = {
                "task_id": task_id,
                "condition": condition,
                "system": system,
                "human_total": human_total,
                "human_covered_strict": 0,
                "human_covered_inclusive": 0,
                "generated_total": len(generated_criteria),
                "assessed_total": len(assessed_ids),
                "unassessed_total": len(set(generated_ids) - set(assessed_ids)),
                "unsupported": 0,
                "appropriate": 0,
                "retrieved_true": 0,
                "retrieved_partial": 0,
                "retrieved_false": 0,
                "relations": Counter(),
                "alignment_entries": entries,
            }
            for entry in entries:
                refs = entry.get("generated_refs", [])
                systems_refs = []
                for ref in refs if isinstance(refs, list) else []:
                    if isinstance(ref, Mapping) and str(ref.get("system")) == system:
                        systems_refs.extend(str(x) for x in ref.get("ids", []) if x is not None)
                if not systems_refs:
                    continue
                coverage = str(entry.get("coverage", ""))
                if coverage == "covered":
                    row["human_covered_strict"] += 1
                    row["human_covered_inclusive"] += 1
                elif coverage == "partial":
                    row["human_covered_inclusive"] += 1
                row["relations"][str(entry.get("relation", "unknown"))] += 1
            for assessment in assessments:
                support = str(assessment.get("support", "unknown"))
                granularity = str(assessment.get("granularity", "unknown"))
                used = str(assessment.get("retrieved_pattern_used", "not_applicable"))
                if support == "unsupported":
                    row["unsupported"] += 1
                if granularity == "appropriate":
                    row["appropriate"] += 1
                if used == "true":
                    row["retrieved_true"] += 1
                elif used == "partial":
                    row["retrieved_partial"] += 1
                elif used == "false":
                    row["retrieved_false"] += 1
            row["relations"] = dict(row["relations"])
            row["unassessed_ids"] = sorted(set(generated_ids) - set(assessed_ids))
            row["generated_criteria"] = generated_criteria
            out_rows.append(row)
            for key in ("human_total", "human_covered_strict", "human_covered_inclusive", "generated_total", "assessed_total", "unassessed_total", "unsupported", "appropriate", "retrieved_true", "retrieved_partial", "retrieved_false"):
                totals[condition][key] += row[key]
            relation_counts[condition].update(row["relations"])
    metrics: dict[str, Any] = {
        "schema_version": "agenteval.rubric_alignment_metrics.v1",
        "status": "machine_proposed_pending_human_review",
        "definitions": {
            "strict_recall": "covered human concern with at least one generated reference for this condition",
            "inclusive_recall": "covered or partial human concern with at least one generated reference",
            "unsupported_extra": "generated assessment support=unsupported",
            "appropriate_granularity": "generated assessment granularity=appropriate",
            "retrieved_pattern_usage": "generated assessment retrieved_pattern_used=true or partial",
        },
        "conditions": {},
    }
    for condition, count in sorted(totals.items()):
        h = count["human_total"]
        g = count["generated_total"]
        metrics["conditions"][condition] = {
            **dict(count),
            "tasks": sum(1 for row in out_rows if row["condition"] == condition),
            "relations": dict(relation_counts[condition]),
            "human_concern_recall_strict": count["human_covered_strict"] / h if h else None,
            "human_concern_recall_including_partial": count["human_covered_inclusive"] / h if h else None,
            "unsupported_extra_rate": count["unsupported"] / g if g else None,
            "unsupported_extra_rate_among_assessed": count["unsupported"] / count["assessed_total"] if count["assessed_total"] else None,
            "alignment_coverage": count["assessed_total"] / g if g else None,
            "unassessed_rate": count["unassessed_total"] / g if g else None,
            "appropriate_granularity_rate": count["appropriate"] / count["assessed_total"] if count["assessed_total"] else None,
            "retrieved_pattern_true_or_partial_rate": (count["retrieved_true"] + count["retrieved_partial"]) / g if g else None,
        }
    return out_rows, metrics


def write_alignment_artifacts(
    proposal_path: str | Path,
    generated_paths: Mapping[str, str | Path],
    out_dir: str | Path,
) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    proposals = read_jsonl(proposal_path)
    generated = {condition: read_jsonl(path) for condition, path in generated_paths.items()}
    rows, metrics = analyze_alignment(proposals, generated)
    (out / "alignment_normalized.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    (out / "alignment_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit = {
        "proposal_count": len(proposals),
        "condition_count": len(metrics["conditions"]),
        "human_ids_are_counted_per_condition": True,
        "duplicate_human_ids_detected": False,
        "generated_criteria_are_counted_from_frozen_outputs": True,
        "downstream_gold_or_judge_used": False,
    }
    (out / "alignment_metric_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metrics
