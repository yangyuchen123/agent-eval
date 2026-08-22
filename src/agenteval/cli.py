"""Command-line interface.

    agenteval eval \
        --cases manifest.json \
        --outputs outputs.json \
        --case-package examples.demo \
        --run-root run/ \
        --model-id my-agent

`--case-package` is a Python module that exposes:

    def build_registry() -> SkillRegistry: ...
    def build_router(registry) -> Router: ...

The framework never imports domain code directly — cases/skills stay
decoupled.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from . import score as score_mod
from .analysis import (judge_rule_agreement, migration_report,
                       render_diagnostics, render_migration,
                       rubric_diagnostics)
from .history import HistoryStore
from .planner import Router
from .protocols import Case
from .report import build_report, evidence_tree_markdown, write_report_artifacts
from .runner import RunConfig, run_eval, write_evidence
from .skills.registry import SkillRegistry


def _load_case_package(name: str) -> Any:
    module = importlib.import_module(name)
    for fn in ("build_registry", "build_router"):
        if not hasattr(module, fn):
            raise SystemExit(
                f"case package {name!r} must define {fn}()")
    return module


def _load_cases(path: Path) -> list[Case]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise SystemExit(f"manifest must contain a 'cases' array: {path}")
    return [Case.from_dict(item) for item in cases]


def _load_outputs(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and all(isinstance(v, str) for v in data.values()):
        return data
    # support {"outputs": {"case_id": "text"}}
    if isinstance(data, dict) and isinstance(data.get("outputs"), dict):
        return {str(k): str(v) for k, v in data["outputs"].items()}
    raise SystemExit(f"outputs must be {{case_id: output_text}}: {path}")


def cmd_eval(args: argparse.Namespace) -> int:
    pkg = _load_case_package(args.case_package)
    registry: SkillRegistry = pkg.build_registry()
    router: Router = pkg.build_router(registry)
    cases = _load_cases(Path(args.cases))
    outputs = _load_outputs(Path(args.outputs))
    print(f"[agenteval] {len(cases)} cases, {len(registry)} skills, "
          f"router={type(router).__name__}")

    run_root = Path(args.run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    plan_root = Path(args.plan_root) if args.plan_root else None
    if plan_root:
        plan_root.mkdir(parents=True, exist_ok=True)
    config = RunConfig(router=router, registry=registry, run_root=run_root,
                       plan_root=plan_root, workers=args.workers,
                       refresh=args.refresh)

    report = run_eval(config, cases, outputs,
                      on_case=lambda cid: print(f"  ✓ {cid}"))
    evidence_root = write_evidence(run_root, report)
    print(f"[agenteval] scored {len(report.evidence)}/{len(cases)} cases, "
          f"failures={len(report.failures)}, skill_cache_hits={report.cache_stats.get('skill_hits', 0)}")
    for failure in report.failures:
        print(f"  ✗ {failure['case_id']}: {failure['error']}")

    # aggregation
    weights = getattr(pkg, "SKILL_WEIGHTS", None) or {}
    aggregator = getattr(pkg, "AGGREGATE", score_mod.weighted_case_score)
    case_scores = {
        cid: aggregator(evidence, weights)
        for cid, evidence in report.evidence.items()
    }
    summary = score_mod.dataset_summary(list(report.evidence.values()),
                                        case_scores, weights)
    final = build_report(list(report.evidence.values()), case_scores, summary,
                         model_id=args.model_id,
                         aggregator_name=getattr(aggregator, "__name__", "custom"))
    artifacts = write_report_artifacts(run_root, final)
    for kind, path in artifacts.items():
        print(f"  [{kind}] {path}")

    if args.verbose:
        for cid, evidence in report.evidence.items():
            print(evidence_tree_markdown(evidence))
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    """Rubric diagnostics over one or more history files."""
    records = HistoryStore.load_many(args.history)
    print(f"[analyze] {len(records)} history records from {len(args.history)} file(s)")
    for rubric_id in args.rubric:
        report = rubric_diagnostics(records, rubric_id, args.version)
        print("\n" + render_diagnostics(report))
        if args.json:
            out = Path(args.json)
            import json
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            print(f"[saved] {out}")

    if args.judge_skill and args.rule_skill:
        agreement = judge_rule_agreement(records, args.judge_skill,
                                         args.rule_skill,
                                         judge_threshold=args.judge_threshold)
        print("\n" + render_agreement(agreement))
    return 0


def render_agreement(agreement: dict[str, Any]) -> str:
    c = agreement.get("confusion")
    lines = [
        f"# Judge↔rule agreement — {agreement.get('judge_skill')} vs "
        f"{agreement.get('rule_skill')}",
        f"paired cases: {agreement.get('n_paired')}",
        f"judge pass rate: {agreement.get('judge_pass_rate')}  "
        f"rule pass rate: {agreement.get('rule_pass_rate')}",
    ]
    if agreement.get("n_paired", 0) < 2:
        lines.append("insufficient paired cases for agreement stats")
        return "\n".join(lines)
    if agreement.get("cohen_kappa") is None:
        # κ undefined (e.g. both raters always pass) but ρ may still exist
        lines.append("κ undefined (rater marginals make p_exp = 1), "
                     f"Spearman ρ = {agreement.get('spearman_rho')}")
        lines.append(
            f"confusion: TP={c['tp']} FP={c['fp']} FN={c['fn']} TN={c['tn']}")
        return "\n".join(lines)
    lines.append(f"Cohen's κ = {agreement['cohen_kappa']}  "
                 f"Spearman ρ = {agreement['spearman_rho']}")
    lines.append(
        f"confusion: TP={c['tp']} FP={c['fp']} FN={c['fn']} TN={c['tn']}")
    kappa = agreement["cohen_kappa"]
    verdict = ("reliable (κ≥0.6)" if kappa >= 0.6 else
               "weak (0.3≤κ<0.6)" if kappa >= 0.3 else
               "unreliable (κ<0.3)")
    lines.append(f"verdict: {verdict}")
    return "\n".join(lines)


def cmd_migrate(args: argparse.Namespace) -> int:
    """Rubric version migration report (ranking preservation, drift)."""
    records = HistoryStore.load_many(args.history)
    print(f"[migrate] {len(records)} history records from {len(args.history)} file(s)")
    report = migration_report(records, args.skill, args.old_version,
                              args.new_version,
                              disagreement_threshold=args.threshold)
    print("\n" + render_migration(report))
    if args.json:
        import json
        out = Path(args.json)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"[saved] {out}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Check that an existing run has evidence + summary for every case."""
    manifest = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases = manifest["cases"] if isinstance(manifest, dict) else manifest
    summary = json.loads((Path(args.run_root) / "summary.json").read_text(encoding="utf-8"))
    scored = {row["case_id"] for row in summary["cases"]}
    missing = [c["case_id"] for c in cases if c["case_id"] not in scored]
    if missing:
        print(f"[verify] MISSING {len(missing)} cases: {missing}")
        return 1
    print(f"[verify] OK — all {len(cases)} cases scored")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agenteval",
                                     description="Agentified evaluation for LLM agents")
    sub = parser.add_subparsers(dest="command", required=True)

    p_eval = sub.add_parser("eval", help="run an evaluation")
    p_eval.add_argument("--cases", required=True, help="case manifest JSON")
    p_eval.add_argument("--outputs", required=True,
                        help="JSON mapping case_id → agent output text")
    p_eval.add_argument("--case-package", required=True,
                        help="Python module exposing build_registry()/build_router()")
    p_eval.add_argument("--run-root", default="run", help="output directory")
    p_eval.add_argument("--plan-root", default=None,
                        help="shared plan cache directory (optional)")
    p_eval.add_argument("--model-id", default="unknown")
    p_eval.add_argument("--workers", type=int, default=1)
    p_eval.add_argument("--refresh", action="store_true",
                        help="ignore plan/results caches")
    p_eval.add_argument("--verbose", action="store_true",
                        help="dump per-case evidence trees")
    p_eval.set_defaults(func=cmd_eval)

    p_verify = sub.add_parser("verify", help="verify a completed run")
    p_verify.add_argument("--cases", required=True)
    p_verify.add_argument("--run-root", default="run")
    p_verify.set_defaults(func=cmd_verify)

    p_analyze = sub.add_parser(
        "analyze", help="rubric diagnostics over evaluation history")
    p_analyze.add_argument("--history", action="append", required=True,
                           help="history.jsonl path (repeatable; merged)")
    p_analyze.add_argument("--rubric", action="append", required=True,
                           help="rubric_id to diagnose (repeatable)")
    p_analyze.add_argument("--version", default=None,
                           help="pin rubric version (default: all)")
    p_analyze.add_argument("--json", default=None,
                           help="also write the report as JSON")
    p_analyze.add_argument("--judge-skill", default=None,
                           help="LLM skill id for judge↔rule agreement")
    p_analyze.add_argument("--rule-skill", default=None,
                           help="rule skill id for judge↔rule agreement")
    p_analyze.add_argument("--judge-threshold", type=float, default=0.5,
                           help="pass threshold for the judge score (default 0.5)")
    p_analyze.set_defaults(func=cmd_analyze)

    p_migrate = sub.add_parser(
        "migrate", help="rubric version migration report")
    p_migrate.add_argument("--history", action="append", required=True,
                           help="history.jsonl path (repeatable; merged)")
    p_migrate.add_argument("--skill", required=True)
    p_migrate.add_argument("--old-version", required=True)
    p_migrate.add_argument("--new-version", required=True)
    p_migrate.add_argument("--threshold", type=float, default=0.2,
                           help="large-disagreement |Δ| threshold")
    p_migrate.add_argument("--json", default=None,
                           help="also write the report as JSON")
    p_migrate.set_defaults(func=cmd_migrate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001
        print(f"[agenteval] error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
