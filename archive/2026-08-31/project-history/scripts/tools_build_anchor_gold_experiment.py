"""Prepare a frozen Gold-backed anchor-resolution experiment.

This tool is offline-only: it writes a manifest and per-condition run config;
it does not call the Judge. The actual batch runner is invoked separately after
explicit approval for the external model calls.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agenteval.meta_eval import load_gold_dir, OctagonDiscovery


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/yang/agent-octagon")
    parser.add_argument("--gold-dir", default="run/meta_eval/failure-handling-blind-v1/gold")
    parser.add_argument("--output", default="run/meta_eval/octagon-real/anchor-resolution-gold-v1")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.repeats != 1:
        raise SystemExit("first Gold-backed comparison is intentionally one call per condition")

    gold = load_gold_dir(args.gold_dir)
    if not gold:
        raise SystemExit("no Gold judgments found")
    if any(item.question_id != "observed_failure_handling" for item in gold):
        raise SystemExit("Gold manifest contains questions other than observed_failure_handling")
    ids = [item.case_id for item in gold]
    if len(set(ids)) != len(ids):
        raise SystemExit("duplicate Gold case IDs")

    discovery = OctagonDiscovery(args.root)
    available = {item.attempt_id: item for item in discovery.discover(only_with_trace=True)}
    missing = [case_id for case_id in ids if case_id not in available]
    if missing:
        raise SystemExit(f"Gold cases missing from Octagon discovery: {missing}")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    conditions = []
    for level, env_version in ((2, "2"), (3, "v3"), (4, "v4"), (5, "5")):
        conditions.append({
            "condition_id": f"{level}-levels",
            "rubric_version_selector": env_version,
            "rubric_level_count": level,
            "attempt_ids": ids,
            "question_ids": ["observed_failure_handling"],
            "repeats": args.repeats,
            "perturbations": ["none"],
            "judge_mode": "agentic_evidence",
            "output": str(output / f"{level}-levels"),
            "external_call_count": len(ids) * args.repeats,
        })
    manifest = {
        "schema_version": "agenteval.anchor_resolution_gold_experiment.v1",
        "gold_dir": str(Path(args.gold_dir)),
        "gold_question_id": "observed_failure_handling",
        "gold_count": len(gold),
        "case_ids": ids,
        "conditions": conditions,
        "control_variables": {
            "same_cases": True,
            "same_question": True,
            "same_trace_snapshots": True,
            "same_model_config": True,
            "same_judge_prompt_path": True,
            "same_evidence_provider": True,
            "same_perturbation": "none",
            "repeats": args.repeats,
        },
        "gold_policy": "human_reviewed_only; Octagon scores are diagnostic and excluded from labels",
        "external_call_count_total": sum(item["external_call_count"] for item in conditions),
        "status": "prepared; no external Judge calls executed by this tool",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (output / "attempt_ids.txt").write_text("\n".join(ids) + "\n")
    print(json.dumps({
        "output": str(output), "gold_count": len(gold),
        "conditions": [x["condition_id"] for x in conditions],
        "external_call_count_total": manifest["external_call_count_total"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
