"""Score GDPVal agent outputs through AgentEval.

Usage:
    # self-check: a perfect deliverable report should score the full rubric
    python evaluate_gdpval.py --outputs outputs_good.json --run-root run/good
    # agent outputs (text reports / file-generation code)
    python evaluate_gdpval.py --outputs outputs_agent.json --run-root run/agent
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))        # examples/gdpval
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))  # framework

from agenteval import (RunConfig, dataset_summary, run_eval,  # noqa: E402
                       write_evidence)
from agenteval.report import build_report, write_report_artifacts  # noqa: E402
from cases import load_cases  # noqa: E402
from skills import build_registry, build_router  # noqa: E402


def _max_possible(evidence) -> float:
    """Sum of positive rubric weights (GDPVal max score)."""
    total = 0.0
    for sid, r in evidence.skill_results.items():
        if sid.startswith("gdpval_judge") and r.diagnostics:
            pass
    # weights live on the skill, not the result — derive from the plan's
    # rubric items via the task data instead
    import json as _json
    tasks = _json.loads((Path(__file__).resolve().parent / "cases.json")
                        .read_text(encoding="utf-8"))["cases"]
    for t in tasks:
        if t["task_id"] == evidence.case_id:
            return round(sum(float(i.get("score") or 0)
                             for i in t["rubric_items"]
                             if float(i.get("score") or 0) > 0), 4)
    return 0.0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="score GDPVal outputs")
    p.add_argument("--outputs", required=True,
                   help="JSON mapping case_id → agent output text")
    p.add_argument("--run-root", type=str, default="run/gdpval")
    p.add_argument("--no-judge", action="store_true",
                   help="skip LLM judge skill (rule checks only)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cases = load_cases()
    outputs = json.loads(Path(args.outputs).read_text(encoding="utf-8"))
    outputs = {str(k): str(v) for k, v in outputs.items()}
    print(f"[gdpval] {len(cases)} cases loaded")

    registry = build_registry(enable_judge=not args.no_judge)
    router = build_router(registry)
    run_root = Path(args.run_root)
    config = RunConfig(router=router, registry=registry, run_root=run_root,
                       plan_root=run_root.parent / "plans",
                       model_id=Path(args.outputs).stem)

    report = run_eval(config, cases, outputs,
                      on_case=lambda cid: print(f"  ✓ {cid}"))
    write_evidence(run_root, report)
    print(f"[gdpval] scored {len(report.evidence)}/{len(cases)} cases, "
          f"failures={len(report.failures)}")

    case_scores = {}
    for cid, ev in report.evidence.items():
        js = [s.score for sid, s in ev.skill_results.items()
              if sid.startswith("gdpval_judge") and s.score is not None]
        case_scores[cid] = round(sum(js), 4) if js else None
    # GDPVal totals are absolute rubric sums (can exceed 1.0), so the
    # framework's [0,1]-assuming summary would filter them. Build a
    # GDPVal-aware summary here; history still records raw totals.
    totals = [s for s in case_scores.values() if s is not None]
    summary = {
        "n_cases": len(cases),
        "n_scored": len(totals),
        "mean_case_score": round(sum(totals) / len(totals), 4) if totals else None,
        "median_case_score": (sorted(totals)[len(totals) // 2]
                              if totals else None),
        "max_possible": {
            cid: _max_possible(ev) for cid, ev in report.evidence.items()},
        "skills": {},
    }
    for sid in registry.skills:
        vals = [r.score for ev in report.evidence.values()
                for s2, r in ev.skill_results.items()
                if s2 == sid and r.score is not None]
        summary["skills"][sid] = {
            "mean": round(sum(vals) / len(vals), 4) if vals else None,
            "n_scored": len(vals)}

    final = build_report(list(report.evidence.values()), case_scores, summary,
                         model_id=Path(args.outputs).stem)
    artifacts = write_report_artifacts(run_root, final)
    for kind, path in artifacts.items():
        print(f"  [{kind}] {path}")

    print("\n=== rubric totals (GDPVal style: Σ satisfied item scores) ===")
    for cid, score in sorted(case_scores.items()):
        print(f"  {cid[:8]}: {score} / {summary['max_possible'].get(cid)}")


if __name__ == "__main__":
    main()
