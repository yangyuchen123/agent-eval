"""RRD recursive decomposition prompt and parser."""
from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from ..backends import LLMBackend
from .evaluator import evaluator_view, materialize_responses
from .models import CalibrationResponse, DecompositionProposal, OptimizationConfig, Rubric


def decomposition_prompt(
    task: str,
    candidates: Sequence[tuple[Rubric, dict[str, int]]],
    responses: Sequence[CalibrationResponse],
    max_children: int,
    config: OptimizationConfig | None = None,
) -> list[dict[str, str]]:
    cfg = config or OptimizationConfig()
    payload = {
        "task": task,
        "candidates": [{"rubric_id": r.rubric_id, "text": r.text, "satisfaction": row} for r, row in candidates],
        "responses": [evaluator_view(x, cfg) for x in responses],
        "max_children": max_children,
        "include_runtrace": cfg.include_runtrace,
    }
    system = """You are the RRD rubric decomposer. Decompose only criteria explicitly supplied as broadness candidates (satisfied by more than the configured number of sample responses). A candidate may remain unchanged if it is already the minimum independently judgeable proposition. If splitting, produce the minimum number of children (at least two, at most the supplied limit). Children must preserve the parent intent exactly, add no new requirements, and each must be independently answerable Yes/No. Use only the supplied artifact/response evidence. Do not use Judge scores, Gold labels, AgentEval taxonomy, quality_group, or runtrace unless it is explicitly present. Output JSON only."""
    user = "Input:\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n\nReturn exactly: {\"proposals\":[{\"parent_rubric_id\":\"R1\",\"action\":\"KEEP|SPLIT\",\"reason\":\"...\",\"children\":[{\"rubric_id\":\"R1.1\",\"text\":\"...\"}]}]}. Include one proposal per candidate. For KEEP children must be []."
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_proposals(parsed: Any, candidates: Sequence[Rubric], max_children: int) -> list[DecompositionProposal]:
    raw = parsed.get("proposals") if isinstance(parsed, dict) else None
    if not isinstance(raw, list):
        raise ValueError("RRD decomposer output must contain list key 'proposals'")
    by_id = {r.rubric_id: r for r in candidates}
    result: list[DecompositionProposal] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("parent_rubric_id") or "")
        if pid not in by_id:
            continue
        action = str(item.get("action") or "KEEP").upper()
        children_raw = item.get("children") if isinstance(item.get("children"), list) else []
        if action != "SPLIT":
            result.append(DecompositionProposal(pid, [], str(item.get("reason") or ""), "keep"))
            continue
        children = []
        for idx, child in enumerate(children_raw[:max_children], 1):
            if isinstance(child, dict) and str(child.get("text") or child.get("criterion") or "").strip():
                children.append(Rubric(str(child.get("rubric_id") or f"{pid}.{idx}"), str(child.get("text") or child.get("criterion")).strip()))
        if len(children) < 2:
            result.append(DecompositionProposal(pid, [], str(item.get("reason") or "insufficient valid children"), "keep"))
        else:
            result.append(DecompositionProposal(pid, children, str(item.get("reason") or ""), "split"))
    for candidate in candidates:
        if candidate.rubric_id not in {x.parent_rubric_id for x in result}:
            result.append(DecompositionProposal(candidate.rubric_id, [], "missing proposal; conservatively keep", "keep"))
    return result


def decompose_with_backend(
    backend: LLMBackend,
    task: str,
    candidates: Sequence[tuple[Rubric, dict[str, int]]],
    responses: Sequence[CalibrationResponse],
    max_children: int,
    config: OptimizationConfig | None = None,
) -> tuple[list[DecompositionProposal], dict[str, Any]]:
    cfg = config or OptimizationConfig()
    prepared = materialize_responses(responses, cfg)
    messages = decomposition_prompt(task, candidates, prepared, max_children, cfg)
    if hasattr(backend, "decompose"):
        from .typed_outputs import DecompositionOutput
        result = backend.decompose(messages, DecompositionOutput, {"rubric_ids": [x[0].rubric_id for x in candidates]})
    else:
        result = backend.infer(messages)
    return parse_proposals(result.get("parsed"), [x[0] for x in candidates], max_children), {
        "response_metadata": result.get("response_metadata"),
        "raw_output_text": result.get("raw_output_text", ""),
        "include_runtrace": cfg.include_runtrace,
    }
