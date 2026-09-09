"""Response-based rubric satisfaction evaluation for RRD."""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from ..backends import LLMBackend
from .artifacts import render_artifact_text, summarize_artifact_path
from .models import CalibrationResponse, OptimizationConfig, Rubric, RubricMetric


def materialize_response(response: CalibrationResponse, config: OptimizationConfig | None = None) -> CalibrationResponse:
    """Attach a deterministic artifact summary. Missing artifacts stay explicit."""
    cfg = config or OptimizationConfig()
    if not response.artifact_paths:
        status = "empty" if cfg.require_artifact else "not_applicable"
        return response.with_artifacts("", status)
    summaries = [summarize_artifact_path(path) for path in response.artifact_paths]
    if any(item.get("status") == "present" for item in summaries):
        status = "present"
    elif any(item.get("status") == "unreadable" for item in summaries):
        status = "unreadable"
    else:
        status = "missing"
    return response.with_artifacts(render_artifact_text(summaries), status)


def materialize_responses(responses: Sequence[CalibrationResponse], config: OptimizationConfig | None = None) -> list[CalibrationResponse]:
    return [materialize_response(x, config) for x in responses]


def evaluator_view(response: CalibrationResponse, config: OptimizationConfig | None = None) -> dict[str, Any]:
    """What the LLM evaluator is allowed to see for one calibration response."""
    cfg = config or OptimizationConfig()
    view: dict[str, Any] = {
        "response_id": response.response_id,
        "artifact_status": response.artifact_status,
    }
    if cfg.include_quality_group_in_prompt:
        view["quality_group"] = response.quality_group
    if cfg.require_artifact or response.artifact_paths:
        view["artifact_paths"] = list(response.artifact_paths)
        view["artifact"] = response.artifact_text or None
    if cfg.include_agent_prose and response.agent_prose:
        view["agent_prose"] = response.agent_prose
    if cfg.include_runtrace and response.runtrace:
        view["runtrace"] = response.runtrace
    if not cfg.require_artifact and not response.artifact_paths:
        view["response"] = response.response
    return view


def evaluation_prompt(
    task: str,
    rubrics: Sequence[Rubric],
    responses: Sequence[CalibrationResponse],
    config: OptimizationConfig | None = None,
) -> list[dict[str, str]]:
    cfg = config or OptimizationConfig()
    payload = {
        "task": task,
        "rubrics": [{"rubric_id": r.rubric_id, "text": r.text} for r in rubrics],
        "responses": [evaluator_view(x, cfg) for x in responses],
        "protocol": {
            "require_artifact": cfg.require_artifact,
            "include_runtrace": cfg.include_runtrace,
            "include_agent_prose": cfg.include_agent_prose,
        },
    }
    if cfg.require_artifact:
        evidence_rule = (
            "Evaluate only the supplied artifact summary for each response. "
            "If artifact_status is empty, missing, or unreadable, the criterion is not satisfied (0). "
            "Do not use agent_prose as a substitute for a missing workbook. "
            "Runtrace is not provided and must not be inferred."
        )
    else:
        evidence_rule = "Evaluate whether each response satisfies each supplied rubric criterion using the supplied evidence fields only."
    system = (
        "You are the RRD response-based rubric evaluator. "
        + evidence_rule
        + " Do not use quality_group, model family, or Gold labels as evidence. "
        "Return a complete binary matrix. 1 means the criterion is satisfied; 0 means it is not satisfied. "
        "Do not score overall quality. Output JSON only."
    )
    user = (
        "Input:\n" + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n\nReturn exactly: {\"matrix\":{\"rubric_id\":{\"response_id\":0}}}. "
        "Include every rubric and every response exactly once. Values must be integers 0 or 1."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _coerce_matrix(parsed: Any, rubrics: Sequence[Rubric], responses: Sequence[CalibrationResponse]) -> dict[str, dict[str, int]]:
    raw = parsed.get("matrix") if isinstance(parsed, dict) else None
    if not isinstance(raw, dict):
        raise ValueError("RRD evaluator output must contain object key 'matrix'")
    result: dict[str, dict[str, int]] = {}
    for rubric in rubrics:
        row = raw.get(rubric.rubric_id)
        if not isinstance(row, dict):
            raise ValueError(f"missing rubric row: {rubric.rubric_id}")
        result[rubric.rubric_id] = {}
        for response in responses:
            value = row.get(response.response_id)
            if isinstance(value, bool):
                value = int(value)
            if isinstance(value, str) and value.strip() in {"0", "1"}:
                value = int(value.strip())
            if value not in {0, 1}:
                raise ValueError(f"matrix value for {rubric.rubric_id}/{response.response_id} is not 0/1")
            result[rubric.rubric_id][response.response_id] = int(value)
    return result


def metrics_from_matrix(matrix: dict[str, dict[str, int]], responses: Sequence[CalibrationResponse], config: Any) -> dict[str, RubricMetric]:
    strong = [x for x in responses if x.quality_group == "strong"]
    weak = [x for x in responses if x.quality_group == "weak"]
    middle = [x for x in responses if x.quality_group == "middle"]
    if not strong or not weak:
        raise ValueError("calibration pool must contain at least one strong and one weak response")
    groups = getattr(config, "broadness_quality_groups", None)
    broad_pool = [x for x in responses if x.quality_group in groups] if groups else list(responses)
    if not broad_pool:
        raise ValueError("broadness_quality_groups selected an empty response pool")
    metrics: dict[str, RubricMetric] = {}
    for rid, row in matrix.items():
        values = [int(row[x.response_id]) for x in responses]
        strong_rate = sum(row[x.response_id] for x in strong) / len(strong)
        weak_rate = sum(row[x.response_id] for x in weak) / len(weak)
        middle_rate = sum(row[x.response_id] for x in middle) / len(middle) if middle else None
        support_rate = sum(values) / len(values)
        discrimination = strong_rate - weak_rate
        broad_count = sum(int(row[x.response_id]) for x in broad_pool)
        metrics[rid] = RubricMetric(
            support_rate=support_rate,
            strong_support_rate=strong_rate,
            weak_support_rate=weak_rate,
            middle_support_rate=middle_rate,
            discrimination=discrimination,
            support_count=sum(values),
            strong_count=len(strong),
            weak_count=len(weak),
            broad_candidate=broad_count > int(config.broad_satisfied_count_threshold),
            misalignment_candidate=weak_rate > strong_rate + float(getattr(config, "misalignment_margin", 0.0)),
        )
    return metrics


def apply_missing_artifact_zeros(
    matrix: dict[str, dict[str, int]],
    responses: Sequence[CalibrationResponse],
    config: OptimizationConfig | None = None,
) -> dict[str, dict[str, int]]:
    cfg = config or OptimizationConfig()
    if not cfg.require_artifact:
        return matrix
    invalid = {x.response_id for x in responses if x.artifact_status != "present"}
    if not invalid:
        return matrix
    return {
        rid: {resp_id: 0 if resp_id in invalid else int(value) for resp_id, value in row.items()}
        for rid, row in matrix.items()
    }


def evaluate_with_backend(
    backend: LLMBackend,
    task: str,
    rubrics: Sequence[Rubric],
    responses: Sequence[CalibrationResponse],
    config: OptimizationConfig | None = None,
) -> tuple[dict[str, dict[str, int]], dict[str, Any]]:
    cfg = config or OptimizationConfig()
    prepared = materialize_responses(responses, cfg)
    prompt_builder = lambda t, r, s: evaluation_prompt(t, r, s, cfg)
    batch_size = max(1, int(getattr(cfg, "response_batch_size", 3) or 3))
    if hasattr(backend, "evaluate_matrix"):
        if hasattr(backend, "response_batch_size"):
            backend.response_batch_size = batch_size
        matrix, metadata = backend.evaluate_matrix(task, list(rubrics), list(prepared), prompt_builder)
    else:
        merged = {r.rubric_id: {} for r in rubrics}
        metas = []
        for offset in range(0, len(prepared), batch_size):
            batch = prepared[offset:offset + batch_size]
            result = backend.infer(evaluation_prompt(task, rubrics, batch, cfg))
            parsed = result.get("parsed")
            batch_matrix = _coerce_matrix(parsed, rubrics, batch)
            for rid, row in batch_matrix.items():
                merged[rid].update(row)
            metas.append(result.get("response_metadata"))
        matrix = merged
        metadata = {"backend": "urllib", "calls": len(metas), "calls_metadata": metas}
    matrix = apply_missing_artifact_zeros(matrix, prepared, cfg)
    metadata = dict(metadata or {})
    metadata.update({
        "artifact_status": {x.response_id: x.artifact_status for x in prepared},
        "include_runtrace": cfg.include_runtrace,
        "require_artifact": cfg.require_artifact,
        "response_batch_size": batch_size,
        "forced_zero_response_ids": [x.response_id for x in prepared if cfg.require_artifact and x.artifact_status != "present"],
    })
    return matrix, metadata


def evaluate_with_callable(
    evaluator: Callable[[str, Sequence[Rubric], Sequence[CalibrationResponse]], Any],
    task: str,
    rubrics: Sequence[Rubric],
    responses: Sequence[CalibrationResponse],
) -> tuple[dict[str, dict[str, int]], dict[str, Any]]:
    value = evaluator(task, rubrics, responses)
    if isinstance(value, tuple) and len(value) == 2:
        matrix, metadata = value
    else:
        matrix, metadata = value, {}
    if isinstance(matrix, dict) and isinstance(matrix.get("matrix"), dict):
        matrix = matrix["matrix"]
    return _coerce_matrix({"matrix": matrix}, rubrics, responses), dict(metadata or {})
