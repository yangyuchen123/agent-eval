"""Aggregate the controlled five-case anchor-resolution experiment (2-9 levels)."""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "run/meta_eval/failure-handling-anchor-small-v1"
LEGACY = ROOT / "run/meta_eval/failure-handling-anchor-v2-v5"
SOURCE_DIRS = {
    2: LEGACY / "2-levels",
    3: BASE / "3-levels",
    4: BASE / "4-levels",
    5: LEGACY / "5-levels",
    6: BASE / "6-levels",
    7: BASE / "7-levels",
    8: BASE / "8-levels",
    9: BASE / "9-levels",
}
OUT = BASE / "curve-analysis.json"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def main() -> None:
    manifest = json.loads((BASE / "manifest.json").read_text())
    case_ids = manifest["case_ids"]
    previous = json.loads(OUT.read_text()) if OUT.exists() else {}
    gold = {
        case_id: float(previous["levels"]["2"]["per_case"][case_id]["gold"])
        for case_id in case_ids
    }
    result: dict[str, Any] = {
        "schema_version": "agenteval.small_anchor_curve.v2",
        "case_ids": case_ids,
        "gold_distribution": dict(sorted(Counter(str(value) for value in gold.values()).items())),
        "levels": {},
        "control_checks": {},
    }
    digests: dict[str, dict[int, set[str]]] = defaultdict(dict)
    models: dict[int, set[str]] = {}
    seeds: dict[int, set[int]] = {}

    for level, source in SOURCE_DIRS.items():
        observations = [x for x in read_jsonl(source / "judgments.jsonl") if x["case_id"] in case_ids]
        if len(observations) != 15:
            raise SystemExit(f"{level} levels: expected 15 observations, got {len(observations)}")
        by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in observations:
            by_case[item["case_id"]].append(item)
            meta = ((item.get("provenance") or {}).get("meta_eval") or {})
            digest = meta.get("trace_digest")
            if digest:
                digests[item["case_id"]].setdefault(level, set()).add(str(digest))
        scores = [float(x["score"]) for x in observations if x.get("score") is not None]
        errors = [abs(float(x["score"]) - gold[x["case_id"]]) for x in observations if x.get("score") is not None]
        squared = [(float(x["score"]) - gold[x["case_id"]]) ** 2 for x in observations if x.get("score") is not None]
        exact = [math.isclose(float(x["score"]), gold[x["case_id"]], abs_tol=1e-9) for x in observations if x.get("score") is not None]
        threshold = [(float(x["score"]) >= 0.5) == (gold[x["case_id"]] >= 0.5) for x in observations if x.get("score") is not None]
        costs = [float(x["cost"]) for x in observations if x.get("cost") is not None]
        latencies = [float(x["latency_ms"]) for x in observations if x.get("latency_ms") is not None]
        input_tokens = [int((x.get("token_usage") or {}).get("input_tokens") or 0) for x in observations]
        requests = [int((x.get("token_usage") or {}).get("requests") or 0) for x in observations]
        tool_calls = [int((x.get("token_usage") or {}).get("tool_calls") or 0) for x in observations]
        per_case = {}
        evidence_jaccards = []
        stable_cases = 0
        status_stable_cases = 0
        for case_id in case_ids:
            items = sorted(by_case[case_id], key=lambda x: x["perturbation_seed"])
            case_scores = [float(x["score"]) for x in items if x.get("score") is not None]
            case_statuses = [x["status"] for x in items]
            if len(set(case_scores)) == 1:
                stable_cases += 1
            if len(set(case_statuses)) == 1:
                status_stable_cases += 1
            refs = [set(x.get("evidence_refs") or []) for x in items]
            pairs = [jaccard(refs[i], refs[j]) for i in range(len(refs)) for j in range(i + 1, len(refs))]
            evidence_jaccards.extend(pairs)
            per_case[case_id] = {
                "gold": gold[case_id],
                "scores": case_scores,
                "mean": statistics.mean(case_scores),
                "std": statistics.stdev(case_scores) if len(case_scores) > 1 else 0.0,
                "mae": statistics.mean(abs(score - gold[case_id]) for score in case_scores),
                "statuses": case_statuses,
                "mean_evidence_jaccard": statistics.mean(pairs) if pairs else None,
            }
        model_values = {
            str((((x.get("provenance") or {}).get("meta_eval") or {}).get("judge_config") or {}).get("model"))
            for x in observations
        }
        rubric_versions = sorted({
            str((((x.get("provenance") or {}).get("meta_eval") or {}).get("judge_config") or {}).get("rubric_version"))
            for x in observations
        })
        anchor_variants = {
            json.dumps(((x.get("provenance") or {}).get("scoring") or {}).get("declared_score_anchors") or [], sort_keys=True)
            for x in observations
        }
        if len(anchor_variants) != 1:
            raise SystemExit(f"{level} levels: inconsistent declared anchor definitions")
        declared_anchors = json.loads(next(iter(anchor_variants)))
        models[level] = model_values
        seeds[level] = {int(x["perturbation_seed"]) for x in observations}
        result["levels"][str(level)] = {
            "source": str(source.relative_to(ROOT)),
            "rubric_versions": rubric_versions,
            "declared_score_anchors": declared_anchors,
            "observations": len(observations),
            "available": len(scores),
            "coverage": len(scores) / len(observations),
            "exact_matches": sum(exact),
            "strict_exact_accuracy": statistics.mean(exact),
            "mae": statistics.mean(errors),
            "rmse": math.sqrt(statistics.mean(squared)),
            "threshold_agreement": statistics.mean(threshold),
            "stable_cases": stable_cases,
            "status_stable_cases": status_stable_cases,
            "mean_per_case_std": statistics.mean(x["std"] for x in per_case.values()),
            "mean_evidence_jaccard": statistics.mean(evidence_jaccards),
            "cost": sum(costs),
            "cost_per_observation": statistics.mean(costs),
            "median_cost_per_observation": statistics.median(costs),
            "p95_cost_per_observation": percentile(costs, 0.95),
            "max_cost_observation": max(costs),
            "mean_latency_ms": statistics.mean(latencies),
            "median_latency_ms": statistics.median(latencies),
            "input_tokens": sum(input_tokens),
            "median_input_tokens": statistics.median(input_tokens),
            "max_input_tokens": max(input_tokens),
            "requests": sum(requests),
            "tool_calls": sum(tool_calls),
            "prediction_distribution": dict(sorted(Counter(str(x["score"]) for x in observations).items())),
            "failure_distribution": dict(sorted(Counter(code for x in observations for code in x.get("failures", [])).items())),
            "per_case": per_case,
        }

    trace_control = {}
    for case_id, by_level in digests.items():
        flattened = {digest for values in by_level.values() for digest in values}
        trace_control[case_id] = {
            "same_trace_digest_across_levels": len(flattened) == 1,
            "digests": sorted(flattened),
            "levels_present": sorted(by_level),
        }
    result["control_checks"] = {
        "models_by_level": {str(k): sorted(v) for k, v in models.items()},
        "same_model_all_levels": len({x for values in models.values() for x in values}) == 1,
        "seeds_by_level": {str(k): sorted(v) for k, v in seeds.items()},
        "same_seeds_all_levels": len({tuple(sorted(v)) for v in seeds.values()}) == 1,
        "trace_by_case": trace_control,
        "same_trace_digest_all_cases": all(x["same_trace_digest_across_levels"] for x in trace_control.values()),
    }
    result["incremental_6_to_9"] = {
        "observations": sum(result["levels"][str(level)]["observations"] for level in range(6, 10)),
        "cost": sum(result["levels"][str(level)]["cost"] for level in range(6, 10)),
        "input_tokens": sum(result["levels"][str(level)]["input_tokens"] for level in range(6, 10)),
        "requests": sum(result["levels"][str(level)]["requests"] for level in range(6, 10)),
        "tool_calls": sum(result["levels"][str(level)]["tool_calls"] for level in range(6, 10)),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "output": str(OUT),
        "control_checks": result["control_checks"],
        "incremental_6_to_9": result["incremental_6_to_9"],
        "summary": {level: {k: result["levels"][str(level)][k] for k in (
            "strict_exact_accuracy", "mae", "rmse", "threshold_agreement",
            "stable_cases", "mean_per_case_std", "cost_per_observation",
            "median_cost_per_observation", "mean_latency_ms"
        )} for level in range(2, 10)},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
