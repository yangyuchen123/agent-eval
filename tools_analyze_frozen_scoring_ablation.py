"""Analyze frozen-evidence scoring-only 2×2 anchor representation ablation."""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "run/meta_eval/frozen-evidence-scoring-ablation-v1"
E2E = ROOT / "run/meta_eval/failure-handling-anchor-wording-ablation-v1/analysis.json"
CELLS = ["A_5_qualitative", "B_5_continuum", "C_6_qualitative", "D_6_continuum"]
GOLD = {
    "att_fa8655f8ce1d": 0.0,
    "att_8ca4f9ec3ba9": 0.5,
    "att_9c539666b31d": 0.5,
    "att_a1bb35bb6955": 1.0,
    "att_07d7cc78f5b0": 1.0,
}


def load_rows() -> list[dict[str, Any]]:
    return [json.loads(x) for x in (OUT / "judgments.jsonl").read_text().splitlines() if x.strip()]


def usage_value(row: dict[str, Any], key: str) -> int:
    usage = row.get("token_usage") or {}
    return int(usage.get(key) or 0)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_case[row["case_id"]].append(row)
    exact = [math.isclose(float(r["score"]), GOLD[r["case_id"]], abs_tol=1e-9) for r in rows]
    errors = [abs(float(r["score"]) - GOLD[r["case_id"]]) for r in rows]
    per_case = {}
    for case_id in GOLD:
        items = sorted(by_case[case_id], key=lambda x: int(x["repeat"]))
        scores = [float(x["score"]) for x in items]
        per_case[case_id] = {
            "gold": GOLD[case_id],
            "scores": scores,
            "mean": statistics.mean(scores),
            "std": statistics.stdev(scores) if len(scores) > 1 else 0.0,
            "mae": statistics.mean(abs(x - GOLD[case_id]) for x in scores),
            "selected_anchor_labels": [x["selected_anchor_label"] for x in items],
            "fact_ids_used": [x.get("fact_ids_used") or [] for x in items],
        }
    return {
        "observations": len(rows),
        "strict_exact_accuracy": statistics.mean(exact),
        "mae": statistics.mean(errors),
        "rmse": math.sqrt(statistics.mean((float(r["score"]) - GOLD[r["case_id"]]) ** 2 for r in rows)),
        "threshold_agreement": statistics.mean((float(r["score"]) >= .5) == (GOLD[r["case_id"]] >= .5) for r in rows),
        "stable_cases": sum(len(set(x["scores"])) == 1 for x in per_case.values()),
        "mean_per_case_std": statistics.mean(x["std"] for x in per_case.values()),
        "mean_latency_ms": statistics.mean(float(x["latency_ms"]) for x in rows),
        "input_tokens": sum(usage_value(x, "input_tokens") for x in rows),
        "output_tokens": sum(usage_value(x, "output_tokens") for x in rows),
        "provider_cost": sum(float((x.get("token_usage") or {}).get("cost") or 0) for x in rows),
        "prediction_distribution": dict(sorted(Counter(str(x["score"]) for x in rows).items())),
        "per_case": per_case,
    }


def effects(cells: dict[str, dict[str, Any]], metric: str) -> dict[str, float]:
    A, B, C, D = (cells[x][metric] for x in CELLS)
    return {
        "wording_continuum_minus_qualitative_at_5": B - A,
        "wording_continuum_minus_qualitative_at_6": D - C,
        "resolution_6_minus_5_under_qualitative": C - A,
        "resolution_6_minus_5_under_continuum": D - B,
        "wording_main_effect": ((B + D) - (A + C)) / 2,
        "resolution_main_effect": ((C + D) - (A + B)) / 2,
        "interaction_difference_in_differences": (D - C) - (B - A),
    }


def main() -> None:
    rows = load_rows()
    by_cell = {cell: [x for x in rows if x["condition"] == cell] for cell in CELLS}
    for cell, items in by_cell.items():
        if len(items) != 15:
            raise SystemExit(f"{cell}: expected 15 rows, found {len(items)}")
    cells = {cell: summarize(items) for cell, items in by_cell.items()}
    metric_names = ["strict_exact_accuracy", "mae", "rmse", "threshold_agreement", "mean_per_case_std"]
    frozen_effects = {metric: effects(cells, metric) for metric in metric_names}
    prior = json.loads(E2E.read_text())
    comparison = {}
    for metric in ("mae", "strict_exact_accuracy"):
        frozen_interaction = frozen_effects[metric]["interaction_difference_in_differences"]
        e2e_interaction = prior["effects"][metric]["interaction_difference_in_differences"]
        comparison[metric] = {
            "end_to_end_interaction": e2e_interaction,
            "frozen_scoring_interaction": frozen_interaction,
            "absolute_interaction_retention_ratio": (
                abs(frozen_interaction) / abs(e2e_interaction) if e2e_interaction else None
            ),
        }
    bundle_digests: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        bundle_digests[row["case_id"]].add(row["bundle_digest"])
    result = {
        "schema_version": "agenteval.frozen_scoring_analysis.v1",
        "gold": GOLD,
        "cells": cells,
        "effects": frozen_effects,
        "end_to_end_comparison": comparison,
        "controls": {
            "observations": len(rows),
            "same_bundle_digest_across_conditions": all(len(x) == 1 for x in bundle_digests.values()),
            "bundle_digests": {k: sorted(v) for k, v in bundle_digests.items()},
            "models": sorted({str(x.get("model")) for x in rows}),
            "no_tools": all((x.get("provenance") or {}).get("tools_available") == [] for x in rows),
        },
        "negative_control": cells["A_5_qualitative"]["per_case"]["att_9c539666b31d"],
    }
    (OUT / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "output": str(OUT / "analysis.json"),
        "cells": {k: {m: v[m] for m in metric_names} for k, v in cells.items()},
        "effects": frozen_effects,
        "comparison": comparison,
        "controls": result["controls"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
