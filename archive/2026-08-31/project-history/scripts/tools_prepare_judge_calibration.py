"""Assemble a reproducible, human-Gold-only Judge calibration bundle.

This is the missing hand-off between human review and Judge calibration:
validated Gold is joined with frozen Judge observations, while diagnostic
runtime/Octagon scores are never used to create labels.  The output is an
append-only calibration manifest, per-case comparison report, and JSONL rows
that can be consumed by later reliability or rubric-evolution jobs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from agenteval.meta_eval import GoldJudgment, load_gold_dir


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise SystemExit(f"{path}:{line_no}: observation must be an object")
        rows.append(value)
    return rows


def _validate_gold(gold: list[GoldJudgment]) -> None:
    keys = [(item.case_id, item.question_id) for item in gold]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    if duplicates:
        raise SystemExit(f"duplicate Gold judgments: {duplicates}")
    for item in gold:
        if not item.expected_status:
            raise SystemExit(f"missing expected_status for {item.case_id}/{item.question_id}")
        if item.expected_score is None and not item.expected_score_by_policy:
            raise SystemExit(f"missing expected score for {item.case_id}/{item.question_id}")
        if item.applicability not in {None, "applicable", "not_applicable"}:
            raise SystemExit(f"invalid applicability for {item.case_id}: {item.applicability}")


def _score(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def build_bundle(*, gold_dir: Path, judgments_path: Path, output: Path,
                 question_id: str | None, judge_mode: str | None,
                 perturbation: str | None, policy_id: str | None) -> dict[str, Any]:
    gold = load_gold_dir(gold_dir)
    _validate_gold(gold)
    gold_by_key = {(item.case_id, item.question_id): item for item in gold}
    observations = _read_jsonl(judgments_path)
    selected = [row for row in observations
                if (question_id is None or row.get("question_id") == question_id)
                and (judge_mode is None or row.get("judge_mode") == judge_mode)
                and (perturbation is None or row.get("perturbation") == perturbation)]
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        key = (str(row.get("case_id", "")), str(row.get("question_id", "")))
        if key in gold_by_key:
            by_key[key].append(row)

    missing_observations = sorted(set(gold_by_key) - set(by_key))
    unmatched_observations = sorted({
        (str(row.get("case_id", "")), str(row.get("question_id", "")))
        for row in selected if (str(row.get("case_id", "")), str(row.get("question_id", ""))) not in gold_by_key
    })
    rows: list[dict[str, Any]] = []
    per_case: dict[str, Any] = {}
    errors: list[float] = []
    status_matches = 0
    total = 0
    for key in sorted(by_key):
        item = gold_by_key[key]
        expected = item.score_for(policy_id)
        if expected is None:
            continue
        case_rows = by_key[key]
        scores = [_score(row.get("score")) for row in case_rows]
        scores = [value for value in scores if value is not None]
        case_errors = [abs(value - expected) for value in scores]
        case_status_matches = sum(row.get("status") == item.expected_status for row in case_rows)
        errors.extend(case_errors)
        status_matches += case_status_matches
        total += len(case_rows)
        per_case[f"{key[0]}|{key[1]}"] = {
            "case_id": key[0], "question_id": key[1],
            "expected_score": expected, "expected_status": item.expected_status,
            "applicability": item.applicability, "expected_stratum": item.expected_stratum,
            "n": len(case_rows), "scores": scores,
            "mean_score": sum(scores) / len(scores) if scores else None,
            "mae": sum(case_errors) / len(case_errors) if case_errors else None,
            "exact_score_rate": sum(math.isclose(v, expected, abs_tol=1e-9) for v in scores) / len(scores) if scores else None,
            "status_accuracy": case_status_matches / len(case_rows) if case_rows else None,
            "gold_evidence": {
                "positive": item.positive_evidence_refs,
                "negative": item.negative_evidence_refs,
                "required": item.required_evidence_refs,
                "missing": item.missing_evidence,
            },
        }
        for row in case_rows:
            rows.append({
                "case_id": key[0], "question_id": key[1],
                "judge_mode": row.get("judge_mode"), "perturbation": row.get("perturbation"),
                "perturbation_seed": row.get("perturbation_seed"),
                "gold": item.to_dict(),
                "judgment": row,
                "comparison": {
                    "expected_score": expected,
                    "score_error": abs(_score(row.get("score")) - expected) if _score(row.get("score")) is not None else None,
                    "score_exact": _score(row.get("score")) is not None and math.isclose(_score(row.get("score")), expected, abs_tol=1e-9),
                    "status_exact": row.get("status") == item.expected_status,
                },
            })

    stratum_counts = Counter(item.expected_stratum or "unspecified" for item in gold)
    score_counts = Counter(str(item.expected_score) for item in gold)
    report = {
        "schema_version": "agenteval.judge_calibration_bundle.v1",
        "gold_policy": "human_only",
        "created_at": "2026-08-28",
        "filters": {"question_id": question_id, "judge_mode": judge_mode, "perturbation": perturbation, "policy_id": policy_id},
        "inputs": {
            "gold_dir": str(gold_dir), "gold_sha256": {str(p.relative_to(gold_dir)): _sha256(p) for p in sorted(gold_dir.glob("*.json"))},
            "judgments_path": str(judgments_path), "judgments_sha256": _sha256(judgments_path),
        },
        "gold": {"count": len(gold), "score_distribution": dict(score_counts), "stratum_distribution": dict(stratum_counts)},
        "observations": {"selected": len(selected), "matched": len(rows), "gold_cases_with_observations": len(by_key),
                         "missing_observations": [f"{a}|{b}" for a, b in missing_observations],
                         "unmatched_observations": [f"{a}|{b}" for a, b in unmatched_observations]},
        "calibration": {"n": total, "score_exact_rate": sum(r["comparison"]["score_exact"] for r in rows) / len(rows) if rows else None,
                        "status_exact_rate": status_matches / total if total else None,
                        "mae": sum(errors) / len(errors) if errors else None,
                        "max_abs_error": max(errors) if errors else None},
        "per_case": per_case,
        "guardrails": [
            "Gold labels are loaded only from human-maintained files.",
            "Octagon scores/statuses and prior Judge outputs are diagnostic observations, never Gold sources.",
            "Missing or unmatched observations are reported rather than silently dropped.",
            "A calibration bundle does not publish or mutate an official rubric.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "calibration.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold-dir", default="run/meta_eval/failure-handling-blind-v1/gold")
    parser.add_argument("--judgments", default="run/meta_eval/failure-handling-anchor-v2-v5/5-levels/judgments.jsonl")
    parser.add_argument("--output", default="run/meta_eval/judge-calibration/failure-handling-v1")
    parser.add_argument("--question-id", default="observed_failure_handling")
    parser.add_argument("--judge-mode", default="agentic_evidence")
    parser.add_argument("--perturbation", default="none")
    parser.add_argument("--policy-id", default=None)
    args = parser.parse_args()
    report = build_bundle(gold_dir=Path(args.gold_dir), judgments_path=Path(args.judgments), output=Path(args.output), question_id=args.question_id, judge_mode=args.judge_mode, perturbation=args.perturbation, policy_id=args.policy_id)
    print(json.dumps({"output": args.output, "gold_count": report["gold"]["count"], "matched_observations": report["observations"]["matched"], "calibration": report["calibration"], "missing_observations": len(report["observations"]["missing_observations"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
