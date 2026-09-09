"""Standalone RRD initial rubric proposal baseline.

This is intentionally separate from the existing A/C/D Generator. It uses the
same frozen calibration responses as context, then hands the proposal to the
RRD optimizer. It is an experiment condition, not a replacement Generator.
"""
from __future__ import annotations
import json
from collections.abc import Sequence
from typing import Any
from ..backends import LLMBackend
from .evaluator import evaluator_view, materialize_responses
from .models import CalibrationResponse, OptimizationConfig, Rubric

def initial_generation_prompt(task: str, responses: Sequence[CalibrationResponse], config: OptimizationConfig | None = None) -> list[dict[str,str]]:
    cfg = config or OptimizationConfig()
    payload={"task":task,"sample_responses":[evaluator_view(x, cfg) for x in responses],"include_runtrace":cfg.include_runtrace}
    system="""You are the standalone RRD initial rubric proposer. Based on the task and supplied sample evidence, propose a compact set of explicit binary evaluation rubrics. Rubrics must be task-grounded, independently judgeable, and useful for distinguishing response quality. Do not use AgentEval grounding/scope/capability taxonomy. Do not output scores, labels, weights, or analysis. Do not invent runtrace evidence. Output JSON only."""
    user="Input:\n"+json.dumps(payload,ensure_ascii=False,indent=2)+"\n\nReturn exactly: {\"rubrics\":[{\"rubric_id\":\"R1\",\"text\":\"...\"}]}. Use 5-20 rubrics and no duplicate criteria."
    return [{"role":"system","content":system},{"role":"user","content":user}]

def parse_initial_rubrics(parsed: Any) -> list[Rubric]:
    raw=parsed.get("rubrics") if isinstance(parsed,dict) else None
    if not isinstance(raw,list): raise ValueError("RRD initial generator output must contain rubrics list")
    result=[]
    for i,x in enumerate(raw):
        if isinstance(x,dict):
            text=str(x.get("text") or x.get("criterion") or "").strip()
            if text: result.append(Rubric(str(x.get("rubric_id") or f"R{i+1}"),text))
    if not result: raise ValueError("RRD initial generator returned no rubrics")
    return result

def generate_initial_with_backend(backend: LLMBackend, task: str, responses: Sequence[CalibrationResponse], config: OptimizationConfig | None = None) -> tuple[list[Rubric],dict[str,Any]]:
    cfg = config or OptimizationConfig()
    prepared = materialize_responses(responses, cfg)
    messages = initial_generation_prompt(task, prepared, cfg)
    if hasattr(backend, "decompose"):
        from .typed_outputs import InitialOutput
        result=backend.infer(messages, output_type=InitialOutput, phase="initial_generation", metadata={"response_ids": [x.response_id for x in prepared]})
    else:
        result=backend.infer(messages)
    return parse_initial_rubrics(result.get("parsed")), {"response_metadata":result.get("response_metadata"),"raw_output_text":result.get("raw_output_text",""),"include_runtrace":cfg.include_runtrace}
