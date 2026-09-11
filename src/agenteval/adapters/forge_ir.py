"""Project a frozen Forge Environment IR rubric into ``agenteval.rubric.v1``.

This adapter is a pure JSON transform. It does not import Benchmark Forge,
does not invent criteria, and does not call a Judge. Duplicate criterion IDs
are rejected so a projected rubric cannot silently collapse scoring dimensions.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..io import atomic_write_json, value_digest
from ..rubrics import RUBRIC_SCHEMA, Rubric

IR_SCHEMA = "benchmark-forge.environment-ir.v1"
PROJECTOR_VERSION = "agenteval.ir-rubric-projector.v1"

_SOURCE_TO_EVIDENCE = {
    "artifact": "artifact",
    "environment_state": "runtime",
    "tool_trace": "runtime",
    "agent_trajectory": "runtime",
    "verifier": "deterministic",
}
_RUNTIME_SOURCES = {"environment_state", "tool_trace", "agent_trajectory"}


class IRRubricProjectionError(ValueError):
    """Forge IR cannot be projected into a frozen AgentEval rubric."""


def _as_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise IRRubricProjectionError(f"{name} must be an object")
    return dict(value)


def _evidence_catalog(ir: Mapping[str, Any]) -> dict[str, str]:
    catalog: dict[str, str] = {}
    for item in ir.get("evidence") or []:
        if not isinstance(item, Mapping):
            continue
        evidence_id = str(item.get("evidence_id") or "").strip()
        source_type = str(item.get("source_type") or "").strip()
        if evidence_id:
            catalog[evidence_id] = source_type
    return catalog


def _map_evidence(refs: list[Any], catalog: Mapping[str, str], criterion_id: str) -> tuple[tuple[str, ...], bool]:
    required: list[str] = []
    runtime = False
    unknown: list[str] = []
    for raw in refs:
        evidence_id = str(raw or "").strip()
        if not evidence_id:
            continue
        source_type = catalog.get(evidence_id)
        if source_type is None:
            unknown.append(evidence_id)
            continue
        mapped = _SOURCE_TO_EVIDENCE.get(source_type)
        if mapped is None:
            raise IRRubricProjectionError(
                f"criterion {criterion_id!r} cites unsupported evidence source {source_type!r}")
        if mapped not in required:
            required.append(mapped)
        if source_type in _RUNTIME_SOURCES:
            runtime = True
    if unknown:
        raise IRRubricProjectionError(
            f"criterion {criterion_id!r} cites unknown evidence_refs: {unknown}")
    return tuple(required), runtime


def _normalize_weight(raw: Any, criterion_id: str) -> float:
    try:
        weight = float(raw)
    except (TypeError, ValueError) as exc:
        raise IRRubricProjectionError(
            f"criterion {criterion_id!r} has a non-numeric weight") from exc
    if weight < 0:
        raise IRRubricProjectionError(f"criterion {criterion_id!r} has a negative weight")
    return weight


def _question_from_criterion(
    criterion: Mapping[str, Any],
    *,
    catalog: Mapping[str, str],
    normalized_weight: float,
    pass_threshold: float | None,
) -> dict[str, Any]:
    criterion_id = str(criterion.get("criterion_id") or "").strip()
    description = str(criterion.get("description") or "").strip()
    if not criterion_id:
        raise IRRubricProjectionError("criterion is missing criterion_id")
    if not description:
        raise IRRubricProjectionError(f"criterion {criterion_id!r} is missing description")
    required, runtime = _map_evidence(list(criterion.get("evidence_refs") or []), catalog, criterion_id)
    if criterion.get("artifact_refs") and "artifact" not in required:
        required = (*required, "artifact")
    if criterion.get("state_refs") and "runtime" not in required:
        required = (*required, "runtime")
        runtime = True
    minimum = criterion.get("minimum_score")
    fail_note = ""
    if minimum is not None:
        fail_note = f" Minimum IR score is {minimum}/100."
    gate_note = " This criterion is a critical gate." if criterion.get("critical_gate") else ""
    threshold_note = ""
    if pass_threshold is not None:
        threshold_note = f" Frozen IR pass_threshold is {pass_threshold}."
    evidence_text = ", ".join(required) if required else "declared IR evidence"
    return {
        "id": criterion_id,
        "question": description,
        "anchors": (
            "0.0 = no material satisfaction; 0.5 = partial satisfaction; "
            f"1.0 = full satisfaction of the frozen IR criterion.{fail_note}{gate_note}{threshold_note}"
        ),
        "evidence": f"Inspect {evidence_text} bound by the frozen IR criterion.",
        "weight": normalized_weight,
        "score_anchors": [
            {"score": 0.0, "description": "No material satisfaction of the frozen IR criterion."},
            {"score": 0.5, "description": "Partial satisfaction; material gaps remain."},
            {"score": 1.0, "description": "The frozen IR criterion is fully satisfied."},
        ],
        "evidence_required": list(required),
        "requires_runtime_evidence": runtime,
        "lineage": [criterion_id],
    }


def project_ir_rubric(ir: Mapping[str, Any], *, source_path: str | None = None) -> Rubric:
    """Convert a frozen Environment IR object into an AgentEval rubric."""
    payload = _as_mapping(ir, "environment IR")
    schema = str(payload.get("schema_version") or "")
    if schema and schema != IR_SCHEMA:
        raise IRRubricProjectionError(f"unsupported IR schema_version {schema!r}")
    if payload.get("frozen") is not True:
        raise IRRubricProjectionError("IR must be frozen before rubric projection")
    ir_checksum = str(payload.get("ir_checksum") or "").strip()
    if not ir_checksum:
        raise IRRubricProjectionError("frozen IR is missing ir_checksum")
    rubric_data = _as_mapping(payload.get("rubric"), "IR rubric")
    rubric_id = str(rubric_data.get("rubric_id") or payload.get("task_id") or "").strip()
    if not rubric_id:
        raise IRRubricProjectionError("IR rubric is missing rubric_id")
    criteria = list(rubric_data.get("criteria") or [])
    if not criteria:
        raise IRRubricProjectionError(f"IR rubric {rubric_id!r} has no criteria")
    ids = [str((item or {}).get("criterion_id") or "").strip() for item in criteria]
    if any(not item for item in ids):
        raise IRRubricProjectionError("every IR criterion requires a non-empty criterion_id")
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise IRRubricProjectionError(
            f"duplicate criterion_id(s) in frozen IR: {duplicates}")
    weights = [_normalize_weight(item.get("weight", 0), ids[index]) for index, item in enumerate(criteria)]
    total = sum(weights)
    if total <= 0:
        raise IRRubricProjectionError("IR rubric must have a positive total weight")
    catalog = _evidence_catalog(payload)
    pass_threshold = rubric_data.get("pass_threshold")
    questions = []
    for criterion, weight in zip(criteria, weights, strict=True):
        questions.append(_question_from_criterion(
            _as_mapping(criterion, "IR criterion"),
            catalog=catalog,
            normalized_weight=weight / total,
            pass_threshold=None if pass_threshold is None else float(pass_threshold),
        ))
    projected = {
        "schema_version": RUBRIC_SCHEMA,
        "rubric_id": rubric_id,
        "version": ir_checksum,
        "description": (
            f"Projected from frozen Environment IR {payload.get('environment_id') or rubric_id}."
        ),
        "allowed_scores": [0.0, 0.5, 1.0],
        "questions": questions,
        "meta_questions": [],
        "provenance": {
            "mode": "projected_from_frozen_ir",
            "projector": PROJECTOR_VERSION,
            "source_path": source_path,
            "environment_id": payload.get("environment_id"),
            "task_id": payload.get("task_id"),
            "ir_checksum": ir_checksum,
            "ir_rubric_id": rubric_data.get("rubric_id"),
            "pass_threshold": pass_threshold,
            "deterministic": rubric_data.get("deterministic"),
            "source_digest": f"sha256:{value_digest(payload)}",
        },
    }
    return Rubric.from_dict(projected)


def project_ir_rubric_file(path: str | Path, output: str | Path | None = None) -> tuple[Rubric, Path | None]:
    import json
    source = Path(path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    rubric = project_ir_rubric(payload, source_path=str(source))
    target = None
    if output is not None:
        target = Path(output).expanduser()
        atomic_write_json(target, rubric.to_dict())
    return rubric, target
