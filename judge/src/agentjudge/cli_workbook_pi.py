"""CLI: run the Pi workbook judge on one frozen GDPval attempt.

Example:
  PYTHONPATH=judge/src python -m agentjudge.cli_workbook_pi \\
    --attempt /home/yang/agent-octagon/data/attempts/att_869a93f9b7f9 \\
    --out run/gdpval-capability-pilot-20260909/workbook_pi_judge_att869
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .gdpval_result import score_100
from .workbook_pi import (
    PROTOCOL_ID,
    collect_result,
    load_official_rubric,
    prepare_workspace,
    build_prompt,
    run_pi_judge,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ATTEMPT = Path("/home/yang/agent-octagon/data/attempts/att_869a93f9b7f9")
DEFAULT_ENV = Path("/home/yang/agent-octagon-envs/gdpval-prepaid-amortization-official")
DEFAULT_TASK = DEFAULT_ENV / "tasks/gdpval_prepaid_amortization_official.json"
DEFAULT_RUBRIC = DEFAULT_ENV / "private/official_rubric.json"
SOURCE_NAMES = [
    "COA.xlsx",
    "Aurisic_Prepaid_Expenses_Jan25.pdf",
    "Aurisic_Prepaid_Expenses_Feb25.pdf",
    "Aurisic_Prepaid_Expenses_Mar25.pdf",
    "Aurisic_Prepaid_Expenses_Apr25.pdf",
    "Aurisic_Prepaid_Insurance.pdf",
]


def _load_env() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _candidate(attempt: Path) -> Path:
    workspace = attempt / "skill_workspace"
    files = sorted(p for p in workspace.glob("*.xlsx") if p.name.casefold() != "coa.xlsx")
    if not files:
        raise SystemExit(f"no candidate xlsx in {workspace}")
    return files[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", type=Path, default=DEFAULT_ATTEMPT)
    parser.add_argument("--task-file", type=Path, default=DEFAULT_TASK)
    parser.add_argument("--rubric", type=Path, default=DEFAULT_RUBRIC)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--thinking", default="off")
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--include-expert", action="store_true")
    parser.add_argument("--no-evaluate", action="store_true")
    parser.add_argument("--prepare-only", action="store_true", help="Write workspace/inspect without calling Pi")
    args = parser.parse_args()
    _load_env()
    attempt = args.attempt
    candidate = _candidate(attempt)
    rubric = load_official_rubric(args.rubric)
    task = json.loads(args.task_file.read_text(encoding="utf-8"))
    sources = [DEFAULT_ENV / "inputs" / name for name in SOURCE_NAMES]
    expert = DEFAULT_ENV / "inputs/official_expert_deliverable.xlsx"
    workspace = args.out
    workspace.mkdir(parents=True, exist_ok=True)
    prepared = prepare_workspace(
        workspace=workspace,
        candidate=candidate,
        rubric_path=args.rubric,
        source_files=sources,
        include_expert=args.include_expert,
        expert_workbook=expert,
        evaluate=not args.no_evaluate,
    )
    prompt = build_prompt(
        task_prompt=str(task.get("prompt") or ""),
        rubric=rubric,
        candidate_name=prepared["candidate_name"],
        source_names=prepared["source_names"],
    )
    (workspace / "judge_prompt.txt").write_text(prompt, encoding="utf-8")
    manifest = {
        "schema_version": "agenteval.workbook_pi_judge_manifest.v1",
        "protocol": PROTOCOL_ID,
        "attempt_id": attempt.name,
        "candidate": str(candidate),
        "rubric": str(args.rubric),
        "n_criteria": len(rubric),
        "include_expert": args.include_expert,
        "evaluate": not args.no_evaluate,
        "evaluated_status": prepared["evaluated_status"],
        "sheet_names": prepared["inspect"].get("sheet_names"),
        "excel_name_limit_31": prepared["inspect"].get("excel_name_limit_31"),
        "gold_label_type": "tier2_proxy_gold_workbook_pi",
        "human_calibrated": False,
    }
    (workspace / "experiment_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.prepare_only:
        print(json.dumps({"ok": True, "prepare_only": True, **{k: manifest[k] for k in ("protocol", "attempt_id", "evaluated_status", "sheet_names")}}, ensure_ascii=False, indent=2))
        return
    pi = run_pi_judge(
        workspace=workspace,
        prompt=prompt,
        provider=args.provider,
        model=args.model,
        timeout=args.timeout,
        thinking=args.thinking,
    )
    collected = collect_result(workspace, rubric)
    summary = {
        "ok": collected.get("ok"),
        "protocol": PROTOCOL_ID,
        "attempt_id": attempt.name,
        "pi": {k: pi[k] for k in ("returncode", "latency_ms", "provider", "model")},
        "evaluated_status": prepared["evaluated_status"],
        "error": collected.get("error"),
        "source": collected.get("source"),
        "score_100": collected.get("score_100"),
        "awarded": (collected.get("judge_review") or {}).get("overall"),
    }
    (workspace / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not collected.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
