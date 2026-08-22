"""Score agent patches against SWE-bench containers via AgentEval.

Feeds predictions.json (from run_pi_agent.py, or any {instance_id:
{model_patch}}) through the framework: patch_applies + test_resolution
skills run inside the per-instance docker containers.

Usage:
    # self-check with the gold patches (harness sanity check — should be 1.0)
    python evaluate_predictions.py --predictions gold --run-root run/gold

    # score the pi agent's patches
    python evaluate_predictions.py --run-root run/pi
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))      # examples/swebench
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))  # framework

from agenteval import (Plan, RuleRouter, RunConfig,  # noqa: E402
                       dataset_summary, run_eval, write_evidence)
from agenteval.report import (build_report,  # noqa: E402
                              write_report_artifacts)
from cases import load_cases  # noqa: E402
from skills import (SKILL_WEIGHTS, build_registry,  # noqa: E402
                    build_router)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="score SWE-bench patches")
    p.add_argument("--predictions", type=str, default=None,
                   help="predictions.json path; special value 'gold' uses "
                        "the bundled reference patches")
    p.add_argument("--run-root", type=str, default="run/swebench")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cases = load_cases()
    print(f"[swebench] {len(cases)} instances loaded")

    if args.predictions == "gold":
        # harness self-check: gold patches must resolve
        gold = {}
        import json as _json
        data = _json.loads(Path(__file__).resolve().parent.joinpath(
            "instances.json").read_text(encoding="utf-8"))
        for inst in data["instances"]:
            gold[inst["instance_id"]] = {"model_patch": inst["patch"]}
        outputs = {cid: gold[cid]["model_patch"] for cid in gold}
        label = "gold"
    else:
        pred_path = Path(args.predictions) if args.predictions else \
            Path(__file__).resolve().parent / "predictions.json"
        preds = json.loads(pred_path.read_text(encoding="utf-8"))
        outputs = {cid: v["model_patch"] for cid, v in preds.items()}
        label = pred_path.stem

    registry = build_registry()
    router = build_router(registry)
    run_root = Path(args.run_root)
    config = RunConfig(router=router, registry=registry, run_root=run_root,
                       plan_root=run_root.parent / "plans",
                       workers=args.workers, model_id=label)

    report = run_eval(config, cases, outputs,
                      on_case=lambda cid: print(f"  ✓ {cid}"))
    write_evidence(run_root, report)
    print(f"[swebench] scored {len(report.evidence)}/{len(cases)} cases, "
          f"failures={len(report.failures)}")

    case_scores = {
        cid: __import__("agenteval").weighted_case_score(ev, SKILL_WEIGHTS)
        for cid, ev in report.evidence.items()
    }
    summary = dataset_summary(list(report.evidence.values()), case_scores,
                              SKILL_WEIGHTS)
    final = build_report(list(report.evidence.values()), case_scores, summary,
                         model_id=label)
    artifacts = write_report_artifacts(run_root, final)
    for kind, path in artifacts.items():
        print(f"  [{kind}] {path}")

    print("\n=== resolution ===")
    for cid, score in sorted(case_scores.items()):
        ev = report.evidence[cid]
        tr = ev.skill_results["test_resolution"]
        print(f"  {cid}: resolved={score == 1.0}  "
              f"f2p_failed={tr.evidence.get('f2p_failed', [])}  "
              f"p2p_failed={tr.evidence.get('p2p_failed', [])}")

    if args.verbose:
        from agenteval.report import evidence_tree_markdown
        for ev in report.evidence.values():
            print(evidence_tree_markdown(ev))


if __name__ == "__main__":
    main()
