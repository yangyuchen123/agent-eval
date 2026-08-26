"""Human-readable meta-evaluation report rendering."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json


def render_report(result: dict[str, Any], *, title: str = "AgentEval Meta-Evaluation Report") -> str:
    manifest, metrics = result.get("manifest", {}), result.get("metrics", {})
    lines = [f"# {title}", "", "## Scope", "", f"- run_id: `{manifest.get('run_id')}`", f"- cases: {manifest.get('case_count')}", f"- judge modes: {', '.join(manifest.get('judge_modes', []))}", f"- repeats: {manifest.get('repeats')}", f"- perturbations: {', '.join(manifest.get('perturbations', []))}", "", "## Reliability status", "", "This report preserves unavailable metrics rather than estimating them without human gold or model usage metadata.", "", "## Failure taxonomy", ""]
    failures = metrics.get("failure_counts", {})
    if failures:
        lines.extend(f"- `{key}`: {value}" for key, value in sorted(failures.items()))
    else:
        lines.append("- No automatically classified failures in the executed observations.")
    lines += ["", "## Groups", "", "| group | n | score mean | score std | exact score/anchor agreement | pairwise score/anchor agreement | status agreement | evidence Jaccard | exact claim identity | latency ms | input tokens | output tokens | cost |", "|---|---:|---:|---:|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for key, group in sorted(metrics.get("by_group", {}).items()):
        score = group.get("stability", {}).get("score", {})
        stability = group.get("stability", {})
        usage = group.get("token_usage", {})
        cost = group.get("cost", {})
        lines.append(f"| `{key}` | {group.get('n')} | {_fmt(score.get('mean'))} | {_fmt(score.get('std'))} | {_fmt(stability.get('exact_score_agreement'))} | {_fmt(stability.get('pairwise_score_agreement'))} | {_fmt(stability.get('exact_status_agreement'))} | {_fmt(stability.get('pairwise_evidence_jaccard'))} | {_fmt(stability.get('exact_claim_identity_agreement'))} | {_fmt(group.get('latency_ms'))} | {_fmt(usage.get('mean_input_tokens'))} | {_fmt(usage.get('mean_output_tokens'))} | {_fmt(cost.get('mean'))} |")
    case_aggregate = metrics.get("by_case_aggregate", {})
    if case_aggregate:
        lines += ["", "## Multi-question case aggregates", "", "| case/mode/perturbation | questions | repeats | mean | std | exact aggregate agreement |", "|---|---:|---:|---:|---:|---|"]
        for key, group in sorted(case_aggregate.items()):
            score = group.get("score", {})
            lines.append(
                f"| `{key}` | {len(group.get('question_ids', []))} | {score.get('n')} | "
                f"{_fmt(score.get('mean'))} | {_fmt(score.get('std'))} | "
                f"{_fmt(group.get('exact_aggregate_agreement'))} |"
            )
    lines += ["", "## Interpretation", "", "The experiment infrastructure distinguishes retrieval, selection, missing-evidence, reasoning, and stochastic failures. A final reliability conclusion requires human-reviewed GoldJudgment records; no Gold agreement is inferred from deterministic scorer outputs.", ""]
    return "\n".join(lines)


def write_report(output_dir: str | Path, result: dict[str, Any]) -> Path:
    path = Path(output_dir) / "META_EVAL_REPORT.md"
    path.write_text(render_report(result), encoding="utf-8")
    return path


def _fmt(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
