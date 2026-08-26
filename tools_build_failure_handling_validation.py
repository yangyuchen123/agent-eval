"""Build a blind, human-review-only failure-handling validation set."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from agentjudge.catalog import EvidenceCatalog
from agenteval.meta_eval import OctagonDiscovery, process_questions_by_id
from agenteval.meta_eval.failure_validation import (
    FailureAttemptScan, candidate_strata, scan_failure_signals,
    select_balanced_scans,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/yang/agent-octagon")
    parser.add_argument("--output", default="run/meta_eval/failure-handling-blind-v1")
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument("--exclude", action="append", default=["att_3f38a0fe1604"])
    parser.add_argument("--exclude-env", action="append", default=["agent-workspace-smoke-test"])
    parser.add_argument("--preview-chars", type=int, default=1600)
    args = parser.parse_args()

    output = Path(args.output)
    packets_dir = output / "packets"
    snapshots_dir = output / "snapshots"
    packets_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    discovery = OctagonDiscovery(args.root)
    attempts = discovery.discover(only_with_trace=True)
    scans: list[FailureAttemptScan] = []
    catalogs: dict[str, EvidenceCatalog] = {}
    attempt_by_id = {attempt.attempt_id: attempt for attempt in attempts}
    for attempt in attempts:
        catalog = EvidenceCatalog.from_attempt_dir(attempt.attempt_dir)
        catalogs[attempt.attempt_id] = catalog
        signals = tuple(scan_failure_signals(catalog.records))
        strata = candidate_strata(signals, score_total=attempt.score_total)
        scans.append(FailureAttemptScan(
            attempt_id=attempt.attempt_id,
            env_name=attempt.env_name,
            task_id=attempt.task_id,
            status=attempt.status,
            score_total=attempt.score_total,
            trace_digest=attempt.trace_digest,
            record_count=len(catalog.records),
            signals=signals,
            candidate_strata=strata,
            diagnostic_notes=(
                "Candidate strata are heuristic discovery labels, not Gold.",
                "Octagon status/score are diagnostic metadata and must not determine the human anchor.",
                "Later success candidates share generic runtime context; they do not prove recovery.",
            ),
        ))

    selected = select_balanced_scans(
        scans, args.count, excluded_attempt_ids=args.exclude,
        excluded_env_names=args.exclude_env,
    )
    rubric_question = process_questions_by_id(version="v3")["observed_failure_handling"]
    manifest_packets = []
    for scan in selected:
        attempt = attempt_by_id[scan.attempt_id]
        catalog = catalogs[scan.attempt_id]
        records = [record.model_dump(mode="json") for record in catalog.records]
        snapshot_path = snapshots_dir / f"{scan.attempt_id}.json"
        snapshot_path.write_text(json.dumps({
            "schema_version": "agenteval.evidence_snapshot.v1",
            "attempt_id": scan.attempt_id,
            "trace_digest": scan.trace_digest,
            "record_count": len(records),
            "records": records,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        by_id = {record["evidence_id"]: record for record in records}
        relevant_ids: list[str] = []
        for signal in scan.signals:
            relevant_ids.extend([signal.evidence_id, *signal.nearby_evidence_refs,
                                 *signal.later_success_candidate_refs])
        relevant_ids = list(dict.fromkeys(ref for ref in relevant_ids if ref in by_id))
        task = discovery.task_prompt(attempt.task_id)
        packet = {
            "schema_version": "agenteval.failure_handling_review_packet.v1",
            "gold_status": "pending_human_review",
            "blind_protocol": {
                "rubric_version": "frozen-2026-08-26.discrete-anchors-v3",
                "rubric_development_attempts_excluded": list(dict.fromkeys(args.exclude)),
                "rubric_development_environments_excluded": list(dict.fromkeys(args.exclude_env)),
                "automatic_labels_are_gold": False,
                "review_instruction": (
                    "Inspect the task and evidence snapshot. Decide applicability, human A-H stratum, "
                    "expected 0/0.5/1 anchor, and required evidence. Do not infer Gold from Octagon score."
                ),
            },
            "case": {
                "case_id": scan.attempt_id,
                "env_name": scan.env_name,
                "task_id": scan.task_id,
                "task": task,
                "trace_digest": scan.trace_digest,
                "evidence_snapshot": str(snapshot_path),
            },
            "rubric_question": rubric_question,
            "automatic_candidate_scan": scan.to_dict(),
            "candidate_evidence_preview": [_preview(by_id[ref], args.preview_chars) for ref in relevant_ids],
            "human_gold": {
                "review_status": "pending",
                "applicability": None,
                "expected_stratum": None,
                "expected_status": None,
                "expected_score": None,
                "positive_evidence_refs": [],
                "negative_evidence_refs": [],
                "required_evidence_refs": [],
                "missing_evidence": [],
                "notes": None,
                "reviewer": None,
                "reviewed_at": None,
            },
            "diagnostic_only": {
                "octagon_status": scan.status,
                "octagon_score_total": scan.score_total,
            },
        }
        packet_path = packets_dir / f"{scan.attempt_id}.json"
        packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest_packets.append({
            "attempt_id": scan.attempt_id,
            "env_name": scan.env_name,
            "task_id": scan.task_id,
            "candidate_strata": list(scan.candidate_strata),
            "signal_counts": scan.signal_counts,
            "record_count": scan.record_count,
            "packet": str(packet_path),
            "snapshot": str(snapshot_path),
            "gold_status": "pending_human_review",
        })

    all_signal_counts = Counter(signal.kind.value for scan in scans for signal in scan.signals)
    candidate_counts = Counter(stratum for scan in scans for stratum in scan.candidate_strata)
    selected_counts = Counter(stratum for scan in selected for stratum in scan.candidate_strata)
    manifest = {
        "schema_version": "agenteval.failure_handling_blind_manifest.v1",
        "created_from": str(args.root),
        "rubric_version": "frozen-2026-08-26.discrete-anchors-v3",
        "gold_policy": "human_only",
        "selection_policy": "balanced candidate strata with cross-environment preference",
        "excluded_attempt_ids": list(dict.fromkeys(args.exclude)),
        "excluded_env_names": list(dict.fromkeys(args.exclude_env)),
        "scan_summary": {
            "attempts_scanned": len(scans),
            "attempts_with_candidate_strata": sum(bool(scan.candidate_strata) for scan in scans),
            "signal_counts": dict(sorted(all_signal_counts.items())),
            "candidate_strata_counts": dict(sorted(candidate_counts.items())),
        },
        "selection_summary": {
            "requested": args.count,
            "selected": len(selected),
            "environment_count": len({scan.env_name for scan in selected}),
            "candidate_strata_counts": dict(sorted(selected_counts.items())),
        },
        "packets": manifest_packets,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({
        "output": str(output),
        **manifest["scan_summary"],
        **manifest["selection_summary"],
    }, ensure_ascii=False, indent=2))


def _preview(record: dict[str, Any], max_chars: int) -> dict[str, Any]:
    content = json.dumps(record.get("content") or {}, ensure_ascii=False, default=str)
    return {
        "evidence_id": record.get("evidence_id"),
        "evidence_class": record.get("evidence_class"),
        "event_type": record.get("event_type"),
        "tool_name": record.get("tool_name"),
        "tool_call_id": record.get("tool_call_id"),
        "agent_id": record.get("agent_id"),
        "parent_agent_id": record.get("parent_agent_id"),
        "content_preview": content[:max_chars],
        "content_truncated": len(content) > max_chars,
    }


if __name__ == "__main__":
    main()
