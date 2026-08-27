"""Run retrieval-only 5/6 × qualitative/continuum rubric sensitivity experiment."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentjudge.catalog import EvidenceCatalog
from agentjudge.http_service import load_project_dotenv
from agentjudge.investigation import RetrievalInvestigationService
from agentjudge.models import EvidenceRecord
from agenteval.meta_eval import OctagonDiscovery, build_resolution_rubric

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "run/meta_eval/retrieval-only-anchor-sensitivity-v1"
CASE_IDS = [
    "att_fa8655f8ce1d", "att_8ca4f9ec3ba9", "att_9c539666b31d",
    "att_a1bb35bb6955", "att_07d7cc78f5b0",
]
CONDITIONS = {
    "A_5_qualitative": (5, "qualitative"),
    "B_5_continuum": (5, "continuum"),
    "C_6_qualitative": (6, "qualitative"),
    "D_6_continuum": (6, "continuum"),
}


def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def build_model() -> Any:
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    key = os.environ.get("JUDGE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("JUDGE_API_KEY/OPENAI_API_KEY is not set")
    return OpenAIChatModel(
        os.environ.get("JUDGE_MODEL", "gpt-5.6-luna"),
        provider=OpenAIProvider(base_url=os.environ.get("JUDGE_BASE_URL"), api_key=key),
    )


def question_for(levels: int, style: str) -> tuple[dict[str, Any], dict[str, Any]]:
    questions, rubric = build_resolution_rubric(levels, style=style)
    question = next(dict(q) for q in questions if q["id"] == "observed_failure_handling")
    return question, rubric


def load_or_create_snapshots(output: Path) -> dict[str, dict[str, Any]]:
    snapshot_dir = output / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    discovery = OctagonDiscovery(os.environ.get("OCTAGON_ROOT", "/home/yang/agent-octagon"))
    available = {x.attempt_id: x for x in discovery.discover(only_with_trace=True)}
    result = {}
    for case_id in CASE_IDS:
        path = snapshot_dir / f"{case_id}.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            attempt = available.get(case_id)
            if attempt is None:
                raise SystemExit(f"attempt unavailable: {case_id}")
            records = [record.model_dump() for record in EvidenceCatalog.from_attempt_dir(attempt.attempt_dir).records]
            payload = {
                "schema_version": "agenteval.retrieval_snapshot.v1",
                "case_id": case_id,
                "task_id": attempt.task_id,
                "env_name": attempt.env_name,
                "task": discovery.task_prompt(attempt.task_id) or f"AgentOctagon task {attempt.task_id}",
                "trace_digest": attempt.trace_digest,
                "record_digest": digest(records),
                "record_count": len(records),
                "records": records,
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if digest(payload["records"]) != payload["record_digest"]:
            raise SystemExit(f"snapshot record digest mismatch: {case_id}")
        result[case_id] = payload
    return result


async def main_async() -> None:
    load_project_dotenv()
    output = Path(os.environ.get("RETRIEVAL_ONLY_OUTPUT", str(OUTPUT)))
    repeats = int(os.environ.get("RETRIEVAL_ONLY_REPEATS", "3"))
    if repeats < 1:
        raise SystemExit("RETRIEVAL_ONLY_REPEATS must be positive")
    output.mkdir(parents=True, exist_ok=True)
    snapshots = load_or_create_snapshots(output)
    model = build_model()
    model_name = os.environ.get("JUDGE_MODEL", "gpt-5.6-luna")

    condition_meta = {}
    for name, (levels, style) in CONDITIONS.items():
        question, rubric = question_for(levels, style)
        condition_meta[name] = {
            "levels": levels, "style": style, "rubric_version": rubric["version"],
            "question_digest": digest(question), "anchor_digest": digest(question["score_anchors"]),
            "declared_score_anchors": question["score_anchors"],
        }
    manifest = {
        "schema_version": "agenteval.retrieval_only_anchor_sensitivity.v1",
        "experiment_id": output.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "api_key_recorded": False,
        "repeats": repeats,
        "expected_observations": len(CASE_IDS) * len(CONDITIONS) * repeats,
        "case_ids": CASE_IDS,
        "conditions": condition_meta,
        "snapshots": {case_id: {
            "record_digest": x["record_digest"], "trace_digest": x.get("trace_digest"),
            "record_count": x["record_count"],
        } for case_id, x in snapshots.items()},
        "controls": {
            "same_snapshot_across_conditions": True,
            "same_task_and_question_text_except_anchor_representation": True,
            "no_score_output": True,
            "no_mandatory_tool_call": True,
            "generic_tools_only": ["search_evidence", "get_evidence", "get_call_context", "get_related_evidence"],
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    path = output / "investigations.jsonl"
    existing: set[tuple[str, str, int]] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                existing.add((row["case_id"], row["condition"], int(row["repeat"])))
    total = manifest["expected_observations"]
    completed = len(existing)
    for case_id in CASE_IDS:
        snapshot = snapshots[case_id]
        records = [EvidenceRecord.model_validate(x) for x in snapshot["records"]]
        for condition, (levels, style) in CONDITIONS.items():
            question, rubric = question_for(levels, style)
            for repeat in range(repeats):
                key = (case_id, condition, repeat)
                if key in existing:
                    continue
                provider = EvidenceCatalog(records)
                service = RetrievalInvestigationService(model, provider)
                started = time.perf_counter()
                result = await service.investigate(
                    task=snapshot["task"], question=question,
                    trace_ref={"record_digest": snapshot["record_digest"]},
                )
                latency_ms = (time.perf_counter() - started) * 1000
                row = {
                    "schema_version": "agenteval.retrieval_only_observation.v1",
                    "case_id": case_id,
                    "question_id": "observed_failure_handling",
                    "condition": condition,
                    "levels": levels,
                    "style": style,
                    "repeat": repeat,
                    "record_digest": snapshot["record_digest"],
                    "trace_digest": snapshot.get("trace_digest"),
                    "record_count": snapshot["record_count"],
                    "rubric_version": rubric["version"],
                    "question_digest": digest(question),
                    "anchor_digest": digest(question["score_anchors"]),
                    **result.model_dump(),
                    "tool_trajectory": service.last_tool_trajectory,
                    "provider_trajectory": service.last_provider_trajectory,
                    "message_history": service.last_message_history,
                    "latency_ms": latency_ms,
                    "token_usage": service.last_usage,
                    "model": model_name,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                if "score" in row or "status" in row or "confidence" in row:
                    raise RuntimeError("retrieval-only output leaked a scoring field")
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                completed += 1
                print(
                    f"[{completed}/{total}] {case_id} {condition} repeat={repeat} "
                    f"tools={len(service.last_tool_trajectory)} refs={len(result.evidence_refs)}",
                    flush=True,
                )

    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    keys = {(x["case_id"], x["condition"], int(x["repeat"])) for x in rows}
    if len(rows) != total or len(keys) != total:
        raise SystemExit(f"expected {total} unique rows; rows={len(rows)} unique={len(keys)}")
    for case_id in CASE_IDS:
        if len({x["record_digest"] for x in rows if x["case_id"] == case_id}) != 1:
            raise SystemExit(f"snapshot changed across conditions: {case_id}")
    print(json.dumps({"output": str(output), "observations": len(rows), "snapshot_control": True}, indent=2))


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
