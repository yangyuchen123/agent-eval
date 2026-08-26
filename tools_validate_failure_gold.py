"""Validate human Gold files against immutable AgentOctagon trace snapshots.

This is metadata validation only. It does not infer labels or alter Judge behavior.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_REF_RE = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+)$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold-dir", default="run/meta_eval/failure-handling-blind-v1/gold")
    parser.add_argument("--attempt-root", default="/home/yang/agent-octagon/data/attempts")
    args = parser.parse_args()
    gold_dir = Path(args.gold_dir)
    attempt_root = Path(args.attempt_root)
    errors: list[str] = []
    count = 0
    for path in sorted(gold_dir.glob("*.json")):
        count += 1
        try:
            gold = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{path}: invalid JSON: {exc}")
            continue
        case_id = gold.get("case_id")
        if not case_id:
            errors.append(f"{path}: missing case_id")
            continue
        score = gold.get("expected_score")
        if score is not None and score not in {0, 0.5, 1, 0.0, 1.0}:
            errors.append(f"{path}: expected_score must be one of 0, 0.5, 1")
        if score == 0.5 and gold.get("expected_stratum") != "B_explicit_failure_partial_recovery":
            errors.append(f"{path}: score 0.5 must use partial-recovery stratum")
        trace = attempt_root / case_id / "trace.jsonl"
        if not trace.is_file():
            errors.append(f"{path}: trace not found: {trace}")
            continue
        refs = []
        for field in ("positive_evidence_refs", "negative_evidence_refs", "required_evidence_refs"):
            refs.extend((field, ref) for ref in gold.get(field, []))
        for field, ref in refs:
            match = _REF_RE.match(str(ref))
            if not match:
                errors.append(f"{path}: {field} has invalid evidence ref {ref!r}")
                continue
            evidence_file = attempt_root / case_id / match.group("file")
            if not evidence_file.is_file():
                errors.append(f"{path}: {field} references missing evidence file {ref!r}")
                continue
            line_count = sum(1 for _ in evidence_file.open(encoding="utf-8", errors="replace"))
            if int(match.group("line")) < 1 or int(match.group("line")) > line_count:
                errors.append(f"{path}: {field} points outside {match.group("file")} ({ref}, {line_count} lines)")
        if score == 0.5 and not gold.get("missing_evidence"):
            errors.append(f"{path}: partial Gold must document missing_evidence")
    print(json.dumps({"gold_count": count, "valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
