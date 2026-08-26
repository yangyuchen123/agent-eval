"""Create diverse, human-review-only Gold packets from real Octagon attempts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agentjudge.catalog import EvidenceCatalog
from agenteval.meta_eval import (GENERIC_RUNTIME_PROCESS_QUESTIONS,
                                 GENERIC_RUNTIME_PROCESS_RUBRIC, OctagonDiscovery)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/yang/agent-octagon")
    parser.add_argument("--output", default="run/meta_eval/gold-review-packets")
    parser.add_argument("--count", type=int, default=30)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    discovery = OctagonDiscovery(args.root)
    attempts = discovery.discover(only_with_trace=True)
    selected = _select_diverse(attempts, args.count)
    manifest = []
    for attempt in selected:
        catalog = EvidenceCatalog.from_attempt_dir(attempt.attempt_dir)
        packet = {
            "schema_version": "agenteval.gold_review_packet.v2",
            "gold_status": "pending_human_review",
            "case_id": attempt.attempt_id,
            "rubric": GENERIC_RUNTIME_PROCESS_RUBRIC,
            "questions": GENERIC_RUNTIME_PROCESS_QUESTIONS,
            "task": {
                "env_name": attempt.env_name,
                "task_id": attempt.task_id,
                "prompt": discovery.task_prompt(attempt.task_id),
            },
            "runtime": attempt.to_dict(),
            "evidence_manifest": catalog.manifest(),
            "evidence_index": [_preview(record.model_dump()) for record in catalog.records],
            "diagnostic_context_not_gold": {
                "octagon_execution_status": attempt.status,
                "octagon_score_total": attempt.score_total,
                "octagon_score_dimensions": attempt.score_dimensions,
            },
            "human_gold_by_question": {
                question["id"]: {
                    "expected_score": None,
                    "expected_status": None,
                    "positive_evidence_refs": [],
                    "negative_evidence_refs": [],
                    "required_evidence_refs": [],
                    "missing_evidence": [],
                    "notes": None,
                    "reviewer": None,
                    "reviewed_at": None,
                }
                for question in GENERIC_RUNTIME_PROCESS_QUESTIONS
            },
        }
        path = output / f"{attempt.attempt_id}.json"
        path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.append({
            "case_id": attempt.attempt_id, "env_name": attempt.env_name,
            "task_id": attempt.task_id, "status": attempt.status,
            "score_total": attempt.score_total, "stratum": _stratum(attempt), "record_count": len(catalog.records),
            "packet": str(path), "gold_status": "pending_human_review",
        })
    (output / "manifest.json").write_text(json.dumps({
        "schema_version": "agenteval.gold_review_manifest.v2",
        "selection_policy": "one-per-environment round-robin, then score/status/trace diversity",
        "packet_count": len(manifest), "packets": manifest,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "packet_count": len(manifest),
                      "environment_count": len({x['env_name'] for x in manifest}),
                      "status_counts": _counts(x["status"] for x in manifest),
                      "stratum_counts": _counts(x["stratum"] for x in manifest)}, ensure_ascii=False, indent=2))


def _select_diverse(attempts: list[Any], count: int) -> list[Any]:
    """Select balanced success/partial/failure cases with environment diversity."""
    strata = {
        "success": [x for x in attempts if x.status == "completed" and x.score_total is not None and x.score_total >= 85],
        "partial": [x for x in attempts if x.score_total is not None and 21 <= x.score_total < 85],
        "failure": [x for x in attempts if x.score_total is not None and x.score_total <= 20],
    }
    # Deterministic ordering prefers richer traces, then stable ids.
    for values in strata.values():
        values.sort(key=lambda x: (-(Path(x.trace_path).stat().st_size if x.trace_path else 0), x.attempt_id))
    targets = {"success": count // 3, "partial": count // 3,
               "failure": count - 2 * (count // 3)}
    selected: list[Any] = []
    used_attempts: set[str] = set()
    used_envs: set[str] = set()
    # First pass: unique environments within and across strata.
    for name in ("success", "partial", "failure"):
        for item in strata[name]:
            if len([x for x in selected if _stratum(x) == name]) >= targets[name]:
                break
            if item.attempt_id in used_attempts or (item.env_name or "unknown") in used_envs:
                continue
            selected.append(item); used_attempts.add(item.attempt_id); used_envs.add(item.env_name or "unknown")
    # Second pass: fill any unavailable stratum slots, preserving attempt uniqueness.
    for name in ("success", "partial", "failure"):
        need = targets[name] - len([x for x in selected if _stratum(x) == name])
        for item in strata[name]:
            if need <= 0:
                break
            if item.attempt_id in used_attempts:
                continue
            selected.append(item); used_attempts.add(item.attempt_id); need -= 1
    # Final fill if a stratum does not have enough eligible records.
    remainder = [x for x in attempts if x.attempt_id not in used_attempts and x.score_total is not None]
    remainder.sort(key=lambda x: (_priority(x), x.attempt_id))
    selected.extend(remainder[: max(0, count - len(selected))])
    return selected[:count]


def _stratum(attempt: Any) -> str:
    score = attempt.score_total
    if attempt.status == "completed" and score is not None and score >= 85:
        return "success"
    if score is not None and score <= 20:
        return "failure"
    return "partial"

def _priority(attempt: Any) -> tuple[Any, ...]:
    status_rank = {"completed": 0, "gave_up": 1, "failed": 2, "interrupted": 3}.get(attempt.status, 4)
    score = attempt.score_total
    bucket = 4 if score is None else (0 if score <= 20 else 1 if score <= 50 else 2 if score <= 80 else 3)
    trace_size = Path(attempt.trace_path).stat().st_size if attempt.trace_path else 0
    return (bucket, status_rank, -trace_size)


def _preview(record: dict[str, Any]) -> dict[str, Any]:
    content = json.dumps(record.get("content") or {}, ensure_ascii=False, default=str)
    return {
        "evidence_id": record.get("evidence_id"), "evidence_class": record.get("evidence_class"),
        "event_type": record.get("event_type"), "tool_name": record.get("tool_name"),
        "agent_id": record.get("agent_id"), "parent_agent_id": record.get("parent_agent_id"),
        "tool_call_id": record.get("tool_call_id"), "file_path": record.get("file_path"),
        "content_preview": content[:1000], "content_truncated": len(content) > 1000,
    }


def _counts(values):
    result = {}
    for value in values: result[str(value)] = result.get(str(value), 0) + 1
    return result


if __name__ == "__main__":
    main()
