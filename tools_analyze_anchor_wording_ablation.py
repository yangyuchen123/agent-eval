"""Analyze the 2x2 anchor-count × anchor-wording ablation."""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "run/meta_eval/failure-handling-anchor-wording-ablation-v1"
CELLS = {
    "A_5_qualitative": {
        "levels": 5, "style": "qualitative",
        "source": ROOT / "run/meta_eval/failure-handling-anchor-v2-v5/5-levels",
    },
    "B_5_continuum": {
        "levels": 5, "style": "continuum",
        "source": OUT_DIR / "5-level-continuum",
    },
    "C_6_qualitative": {
        "levels": 6, "style": "qualitative",
        "source": OUT_DIR / "6-level-qualitative",
    },
    "D_6_continuum": {
        "levels": 6, "style": "continuum",
        "source": ROOT / "run/meta_eval/failure-handling-anchor-small-v1/6-levels",
    },
}
CASE_IDS = [
    "att_fa8655f8ce1d", "att_8ca4f9ec3ba9", "att_9c539666b31d",
    "att_a1bb35bb6955", "att_07d7cc78f5b0",
]
GOLD = {
    "att_fa8655f8ce1d": 0.0,
    "att_8ca4f9ec3ba9": 0.5,
    "att_9c539666b31d": 0.5,
    "att_a1bb35bb6955": 1.0,
    "att_07d7cc78f5b0": 1.0,
}


def read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def jac(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def summarize(observations: list[dict[str, Any]]) -> dict[str, Any]:
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in observations:
        by_case[item["case_id"]].append(item)
    scores = [float(x["score"]) for x in observations]
    errors = [abs(float(x["score"]) - GOLD[x["case_id"]]) for x in observations]
    exact = [math.isclose(float(x["score"]), GOLD[x["case_id"]], abs_tol=1e-9) for x in observations]
    threshold = [(float(x["score"]) >= .5) == (GOLD[x["case_id"]] >= .5) for x in observations]
    per_case = {}
    pair_jaccards = []
    stable = 0
    for case_id in CASE_IDS:
        items = sorted(by_case[case_id], key=lambda x: x["perturbation_seed"])
        values = [float(x["score"]) for x in items]
        if len(set(values)) == 1:
            stable += 1
        refs = [set(x.get("evidence_refs") or []) for x in items]
        pairs = [jac(refs[i], refs[j]) for i in range(3) for j in range(i + 1, 3)]
        pair_jaccards.extend(pairs)
        per_case[case_id] = {
            "gold": GOLD[case_id],
            "scores": values,
            "mean": statistics.mean(values),
            "std": statistics.stdev(values),
            "mae": statistics.mean(abs(v - GOLD[case_id]) for v in values),
            "statuses": [x["status"] for x in items],
            "mean_evidence_jaccard": statistics.mean(pairs),
        }
    costs = [float(x["cost"]) for x in observations]
    return {
        "observations": len(observations),
        "strict_exact_accuracy": statistics.mean(exact),
        "mae": statistics.mean(errors),
        "rmse": math.sqrt(statistics.mean((float(x["score"]) - GOLD[x["case_id"]]) ** 2 for x in observations)),
        "threshold_agreement": statistics.mean(threshold),
        "stable_cases": stable,
        "mean_per_case_std": statistics.mean(x["std"] for x in per_case.values()),
        "mean_evidence_jaccard": statistics.mean(pair_jaccards),
        "cost": sum(costs),
        "cost_per_observation": statistics.mean(costs),
        "median_cost_per_observation": statistics.median(costs),
        "mean_latency_ms": statistics.mean(float(x["latency_ms"]) for x in observations),
        "input_tokens": sum(int((x.get("token_usage") or {}).get("input_tokens") or 0) for x in observations),
        "prediction_distribution": dict(sorted(Counter(str(x["score"]) for x in observations).items())),
        "failure_distribution": dict(sorted(Counter(code for x in observations for code in x.get("failures", [])).items())),
        "per_case": per_case,
    }


def delta(left: dict[str, Any], right: dict[str, Any], metric: str) -> float:
    return float(right[metric]) - float(left[metric])


def main() -> None:
    result: dict[str, Any] = {
        "schema_version": "agenteval.anchor_wording_ablation.v1",
        "case_ids": CASE_IDS,
        "gold": GOLD,
        "cells": {},
        "effects": {},
        "control_checks": {},
    }
    raw_by_cell = {}
    all_models = set()
    all_seed_sets = set()
    trace_by_case: dict[str, set[str]] = defaultdict(set)
    for name, spec in CELLS.items():
        observations = [x for x in read(spec["source"] / "judgments.jsonl") if x["case_id"] in CASE_IDS]
        if len(observations) != 15:
            raise SystemExit(f"{name}: expected 15 observations, got {len(observations)}")
        raw_by_cell[name] = observations
        summary = summarize(observations)
        first = observations[0]
        scoring = (first.get("provenance") or {}).get("scoring") or {}
        meta = (first.get("provenance") or {}).get("meta_eval") or {}
        summary.update({
            "levels": spec["levels"],
            "style": spec["style"],
            "source": str(spec["source"].relative_to(ROOT)),
            "rubric_version": (meta.get("judge_config") or {}).get("rubric_version"),
            "declared_score_anchors": scoring.get("declared_score_anchors") or [],
        })
        result["cells"][name] = summary
        seed_set = tuple(sorted({int(x["perturbation_seed"]) for x in observations}))
        all_seed_sets.add(seed_set)
        for item in observations:
            item_meta = (item.get("provenance") or {}).get("meta_eval") or {}
            all_models.add(str((item_meta.get("judge_config") or {}).get("model")))
            if item_meta.get("trace_digest"):
                trace_by_case[item["case_id"]].add(str(item_meta["trace_digest"]))

    A, B, C, D = (result["cells"][key] for key in CELLS)
    metrics = [
        "strict_exact_accuracy", "mae", "rmse", "threshold_agreement",
        "mean_per_case_std", "mean_evidence_jaccard", "cost_per_observation",
    ]
    effects = {}
    for metric in metrics:
        wording_at_5 = delta(A, B, metric)  # continuum - qualitative
        wording_at_6 = delta(C, D, metric)
        resolution_qual = delta(A, C, metric)  # 6 - 5
        resolution_cont = delta(B, D, metric)
        effects[metric] = {
            "wording_continuum_minus_qualitative_at_5": wording_at_5,
            "wording_continuum_minus_qualitative_at_6": wording_at_6,
            "resolution_6_minus_5_under_qualitative": resolution_qual,
            "resolution_6_minus_5_under_continuum": resolution_cont,
            "wording_main_effect": ((B[metric] + D[metric]) - (A[metric] + C[metric])) / 2,
            "resolution_main_effect": ((C[metric] + D[metric]) - (A[metric] + B[metric])) / 2,
            "interaction_difference_in_differences": wording_at_6 - wording_at_5,
        }
    result["effects"] = effects

    # Paired observation-level decomposition using identical case/seed keys.
    keyed = {}
    for cell, observations in raw_by_cell.items():
        keyed[cell] = {(x["case_id"], int(x["perturbation_seed"])): x for x in observations}
    comparisons = {}
    for left, right in (("A_5_qualitative", "B_5_continuum"),
                        ("C_6_qualitative", "D_6_continuum"),
                        ("A_5_qualitative", "C_6_qualitative"),
                        ("B_5_continuum", "D_6_continuum")):
        rows = []
        for key in sorted(keyed[left]):
            lscore = float(keyed[left][key]["score"])
            rscore = float(keyed[right][key]["score"])
            g = GOLD[key[0]]
            rows.append({
                "case_id": key[0], "seed": key[1], "left_score": lscore, "right_score": rscore,
                "score_delta": rscore - lscore,
                "absolute_error_delta": abs(rscore - g) - abs(lscore - g),
            })
        comparisons[f"{left}_vs_{right}"] = {
            "right_better_error_count": sum(x["absolute_error_delta"] < 0 for x in rows),
            "equal_error_count": sum(math.isclose(x["absolute_error_delta"], 0, abs_tol=1e-12) for x in rows),
            "right_worse_error_count": sum(x["absolute_error_delta"] > 0 for x in rows),
            "mean_absolute_error_delta": statistics.mean(x["absolute_error_delta"] for x in rows),
            "rows": rows,
        }
    result["paired_comparisons"] = comparisons
    result["control_checks"] = {
        "models": sorted(all_models),
        "same_model": len(all_models) == 1,
        "seed_sets": [list(x) for x in sorted(all_seed_sets)],
        "same_seeds": len(all_seed_sets) == 1,
        "same_trace_digest_by_case": {case_id: len(values) == 1 for case_id, values in trace_by_case.items()},
        "same_trace_digest_all_cases": all(len(values) == 1 for values in trace_by_case.values()),
    }
    result["new_conditions"] = {
        "observations": B["observations"] + C["observations"],
        "cost": B["cost"] + C["cost"],
        "input_tokens": B["input_tokens"] + C["input_tokens"],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "output": str(OUT_DIR / "analysis.json"),
        "cells": {name: {k: cell[k] for k in metrics} for name, cell in result["cells"].items()},
        "effects": effects,
        "new_conditions": result["new_conditions"],
        "control_checks": result["control_checks"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
