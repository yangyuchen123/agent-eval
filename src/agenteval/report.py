"""Auditable report: evidence tree → summary / leaderboard / markdown.

The report is the *reasoning that justifies the score*: for every case it
links the plan (why these skills), each skill result (subscores + reasons),
and the agent output — a complete, inspectable chain.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .io import atomic_write_json
from .protocols import CaseEvidence, REPORT_SCHEMA


def build_report(
    cases: list[CaseEvidence],
    case_scores: Mapping[str, float | None],
    summary: Mapping[str, Any],
    *,
    model_id: str = "unknown",
    aggregator_name: str = "weighted_case_score",
) -> dict[str, Any]:
    rows = []
    for evidence in cases:
        score = case_scores.get(evidence.case_id)
        rows.append({
            "case_id": evidence.case_id,
            "score": score,
            "skills": {
                sid: {
                    "score": r.score,
                    "status": r.status,
                    # Preserve Judge/tool provenance in the report index while
                    # the full evidence tree remains under evidence/.
                    "provenance": r.diagnostics.get("judge_provenance", r.diagnostics.get("provenance", {})),
                }
                for sid, r in sorted(evidence.skill_results.items())
            },
        })
    return {
        "schema_version": REPORT_SCHEMA,
        "model_id": model_id,
        "aggregator": aggregator_name,
        "summary": dict(summary),
        "cases": rows,
    }


def write_report_artifacts(run_root: Path, report: dict[str, Any]) -> dict[str, str]:
    """Write summary.json, leaderboard.json/.csv, LEADERBOARD.md."""
    out: dict[str, str] = {}
    summary_path = run_root / "summary.json"
    atomic_write_json(summary_path, report)
    out["summary_json"] = str(summary_path)

    rows = report["cases"]
    lb_path = run_root / "leaderboard.csv"
    with open(lb_path, "w", encoding="utf-8") as f:
        f.write("case_id,score\n")
        for row in sorted(rows, key=lambda r: (r["score"] is None, -(r["score"] or -1))):
            f.write(f"{row['case_id']},{'' if row['score'] is None else row['score']}\n")
    out["leaderboard_csv"] = str(lb_path)

    md = _leaderboard_markdown(report)
    md_path = run_root / "LEADERBOARD.md"
    md_path.write_text(md, encoding="utf-8")
    out["leaderboard_md"] = str(md_path)
    return out


def _leaderboard_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"# Leaderboard — {report['model_id']}",
        "",
        f"- aggregator: `{report['aggregator']}`",
        f"- cases scored: {summary.get('n_scored')}/{summary.get('n_cases')}",
        f"- mean case score: {summary.get('mean_case_score')}",
        "",
        "## Per-skill means",
        "",
        "| skill | mean | n |",
        "| --- | --- | --- |",
    ]
    for skill_id, stats in (summary.get("skills") or {}).items():
        lines.append(f"| {skill_id} | {stats['mean']} | {stats['n_scored']} |")
    lines += ["", "## Per-case scores", "",
              "| case | score |", "| --- | --- |"]
    for row in sorted(report["cases"], key=lambda r: (r["score"] is None, -(r["score"] or -1))):
        lines.append(f"| {row['case_id']} | {row['score']} |")
    lines.append("")
    lines.append("> Full auditable evidence (plans, prompts, sub-scores, reasons)")
    lines.append("> lives under `evidence/` and `metric_cache/`.")
    return "\n".join(lines)


def evidence_tree_markdown(evidence: CaseEvidence) -> str:
    """Render one case's evidence tree as readable markdown."""
    lines = [
        f"## {evidence.case_id}",
        "",
        "### Agent output",
        "```",
        evidence.output[:2000],
        "```",
        "",
        "### Plan",
        "",
    ]
    for item in evidence.plan.selected_skills:
        lines.append(f"- **{item['skill_id']}** ({item['role']}): {item['reason']}")
    for item in evidence.plan.skipped_skills:
        lines.append(f"- ~~{item['skill_id']}~~ skipped: {item['reason']}")
    lines.append("")
    for skill_id, result in sorted(evidence.skill_results.items()):
        lines.append(f"### {skill_id} — {result.status} — "
                     f"score={result.score}")
        for key, value in result.subscores.items():
            lines.append(f"- {key}: {value}")
        for key, reason in result.reasons.items():
            lines.append(f"  - *{key}*: {reason}")
    return "\n".join(lines)
