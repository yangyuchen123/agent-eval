"""Run frozen fine-grained process questions over real Octagon attempts.

Use META_EVAL_QUESTION_IDS to select a bounded subset; by default all five
independent discrete-anchor dimensions are included.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

from agentjudge.catalog import EvidenceCatalog
from agentjudge.baselines import FullTraceJudgeService, StaticRetrievalJudgeService
from agentjudge.http_service import load_project_dotenv
from agentjudge.models import EvidenceRecord, JudgeRequest
from agentjudge.service import QuestionJudgeService
from agenteval.meta_eval import (EvidenceSnapshot, GENERIC_RUNTIME_PROCESS_RUBRIC,
                                 MetaCase, MetaEvalRunner, OctagonDiscovery,
                                 lengthen, load_gold_dir, process_questions_by_id, reorder)

load_project_dotenv()

def _selected_rubric() -> tuple[dict, dict[str, dict]]:
    requested_levels = os.environ.get("META_EVAL_ANCHOR_LEVELS")
    if requested_levels:
        from agenteval.meta_eval import build_resolution_rubric
        anchor_style = os.environ.get("META_EVAL_ANCHOR_STYLE", "continuum")
        questions, rubric = build_resolution_rubric(int(requested_levels), style=anchor_style)
        return rubric, {str(q["id"]): dict(q) for q in questions}
    version = os.environ.get("META_EVAL_RUBRIC_VERSION", "current")
    if version == "v4":
        from agenteval.meta_eval import GENERIC_RUNTIME_PROCESS_RUBRIC_V4
        return GENERIC_RUNTIME_PROCESS_RUBRIC_V4, process_questions_by_id(version="v4")
    if version == "v3":
        from agenteval.meta_eval import GENERIC_RUNTIME_PROCESS_RUBRIC_V3
        return GENERIC_RUNTIME_PROCESS_RUBRIC_V3, process_questions_by_id(version="v3")
    if version in {"2", "two", "two_level"}:
        from agenteval.meta_eval import GENERIC_RUNTIME_PROCESS_RUBRIC_TWO_LEVEL, GENERIC_RUNTIME_PROCESS_QUESTIONS_TWO_LEVEL
        return GENERIC_RUNTIME_PROCESS_RUBRIC_TWO_LEVEL, {str(q["id"]): dict(q) for q in GENERIC_RUNTIME_PROCESS_QUESTIONS_TWO_LEVEL}
    if version in {"5", "five", "five_level"}:
        from agenteval.meta_eval import GENERIC_RUNTIME_PROCESS_RUBRIC_FIVE_LEVEL, GENERIC_RUNTIME_PROCESS_QUESTIONS_FIVE_LEVEL
        return GENERIC_RUNTIME_PROCESS_RUBRIC_FIVE_LEVEL, {str(q["id"]): dict(q) for q in GENERIC_RUNTIME_PROCESS_QUESTIONS_FIVE_LEVEL}
    return GENERIC_RUNTIME_PROCESS_RUBRIC, process_questions_by_id()


FROZEN_RUBRIC, FROZEN_QUESTIONS = _selected_rubric()

DEFAULT_ATTEMPTS = [
    "att_3f38a0fe1604",  # short workspace task
    "att_3d8ecd7a1800",  # agent parallel scheduling, long wire
    "att_83a41bf1ced2",  # validation case, gave_up
    "att_9ede41110391",  # edit-contract repair, partial/gave_up
    "att_d348670523d9",  # artifact-heavy GDPVal success
    "att_d437e26c7bbc",  # visitor appointment failure
]


def build_model():
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    key = os.environ.get("JUDGE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("JUDGE_API_KEY/OPENAI_API_KEY is not set")
    return OpenAIChatModel(os.environ.get("JUDGE_MODEL", "gpt-5.6-luna"), provider=OpenAIProvider(base_url=os.environ.get("JUDGE_BASE_URL"), api_key=key))


def main() -> None:
    octagon_root = os.environ.get("OCTAGON_ROOT", "/home/yang/agent-octagon")
    attempt_ids = [x.strip() for x in os.environ.get("META_EVAL_ATTEMPT_IDS", ",".join(DEFAULT_ATTEMPTS)).split(",") if x.strip()]
    repeats = int(os.environ.get("META_EVAL_REPEATS", "3"))
    question_ids = [
        x.strip() for x in os.environ.get(
            "META_EVAL_QUESTION_IDS", ",".join(FROZEN_QUESTIONS)
        ).split(",") if x.strip()
    ]
    unknown_questions = [qid for qid in question_ids if qid not in FROZEN_QUESTIONS]
    if unknown_questions:
        raise SystemExit(f"unknown rubric question ids: {unknown_questions}")
    output = Path(os.environ.get("META_EVAL_OUTPUT", "run/meta_eval/octagon-real/multi-case-generic-process-v2"))
    discovery = OctagonDiscovery(octagon_root)
    available = {x.attempt_id: x for x in discovery.discover(only_with_trace=True)}
    gold_by_key = {}
    gold_dir = os.environ.get("META_EVAL_GOLD_DIR")
    if gold_dir:
        gold_by_key = {(item.case_id, item.question_id): item for item in load_gold_dir(gold_dir)}
    cases: list[MetaCase] = []
    for attempt_id in attempt_ids:
        attempt = available.get(attempt_id)
        if attempt is None:
            raise SystemExit(f"attempt not found or has no trace: {attempt_id}")
        catalog = EvidenceCatalog.from_attempt_dir(attempt.attempt_dir)
        snapshot = EvidenceSnapshot.from_records([record.model_dump() for record in catalog.records])
        prompt = discovery.task_prompt(attempt.task_id) or f"AgentOctagon task {attempt.task_id} in {attempt.env_name}"
        for question_id in question_ids:
            question = FROZEN_QUESTIONS[question_id]
            cases.append(MetaCase(
                case_id=attempt.attempt_id,
                question_id=question_id,
                case={"case_id": attempt.attempt_id, "task": prompt, "metadata": {"env_name": attempt.env_name, "task_id": attempt.task_id}},
                question=question,
                rubric=FROZEN_RUBRIC,
                evidence=snapshot,
                gold=gold_by_key.get((attempt.attempt_id, question_id)),
                trace_digest=attempt.trace_digest,
                judge_config={"model": os.environ.get("JUDGE_MODEL", "gpt-5.6-luna"), "temperature": os.environ.get("JUDGE_TEMPERATURE", "unset"), "rubric_version": FROZEN_RUBRIC["version"], "anchor_scores": [anchor["score"] for anchor in question["score_anchors"]]},
            ))
    model = build_model()

    def agentic_judge(case: MetaCase, snapshot: EvidenceSnapshot):
        async def run():
            provider = EvidenceCatalog([EvidenceRecord.model_validate(record) for record in snapshot.records])
            request = _request(case, snapshot)
            service = QuestionJudgeService(model, provider)
            judgment = await service.evaluate(request)
            return _result(judgment, {"query_trajectory": service.last_query_trajectory,
                                      "snapshot_digest": snapshot.snapshot_digest,
                                      "scoring": service.last_scoring_provenance}, service.last_usage)
        return asyncio.run(run())

    def full_trace_judge(case: MetaCase, snapshot: EvidenceSnapshot):
        async def run():
            records = [EvidenceRecord.model_validate(record) for record in snapshot.records]
            service = FullTraceJudgeService(model)
            judgment = await service.evaluate(_request(case, snapshot), records)
            return _result(judgment, service.last_provenance, service.last_usage)
        return asyncio.run(run())

    def static_retrieval_judge(case: MetaCase, snapshot: EvidenceSnapshot):
        async def run():
            provider = EvidenceCatalog([EvidenceRecord.model_validate(record) for record in snapshot.records])
            service = StaticRetrievalJudgeService(model, top_k=int(os.environ.get("META_EVAL_STATIC_TOP_K", "20")))
            judgment = await service.evaluate(_request(case, snapshot), provider)
            return _result(judgment, service.last_provenance, service.last_usage)
        return asyncio.run(run())

    mode_map = {"agentic_evidence": agentic_judge, "full_trace": full_trace_judge,
                "static_retrieval": static_retrieval_judge}
    selected_modes = [name.strip() for name in os.environ.get("META_EVAL_JUDGE_MODES", "agentic_evidence").split(",") if name.strip()]
    unknown_modes = [name for name in selected_modes if name not in mode_map]
    if unknown_modes:
        raise SystemExit(f"unknown judge modes: {unknown_modes}")

    perturbation_map = {
        "none": ("none", lambda snapshot, _seed: snapshot),
        "order_shuffle": ("order_shuffle", lambda snapshot, seed: reorder(snapshot, seed)),
        "trace_2x": ("trace_2x", lambda snapshot, seed: lengthen(snapshot, 2, seed=seed)),
        "trace_5x": ("trace_5x", lambda snapshot, seed: lengthen(snapshot, 5, seed=seed)),
    }
    selected = [name.strip() for name in os.environ.get("META_EVAL_PERTURBATIONS", "none").split(",") if name.strip()]
    unknown = [name for name in selected if name not in perturbation_map]
    if unknown:
        raise SystemExit(f"unknown perturbations: {unknown}")
    result = MetaEvalRunner(output).run(cases, {name: mode_map[name] for name in selected_modes}, repeats=repeats,
                                        perturbations=[perturbation_map[name] for name in selected],
                                        seed=int(os.environ.get("META_EVAL_SEED", "20260826")))
    print(json.dumps({"output": str(output), "manifest": result["manifest"],
                      "metrics": result["metrics"]}, ensure_ascii=False, indent=2))


def _request(case: MetaCase, snapshot: EvidenceSnapshot) -> JudgeRequest:
    return JudgeRequest(case=case.case, rubric=case.rubric, rubric_question=case.question,
                        agent_output=case.agent_output,
                        trace_ref={"snapshot_digest": snapshot.snapshot_digest},
                        metadata={"meta_eval": True, "frozen_policy": FROZEN_RUBRIC["version"]})


def _result(judgment, provenance, usage):
    cost = usage.get("cost") if usage else None
    try:
        cost = float(cost) if cost is not None else None
    except (TypeError, ValueError):
        cost = None
    return {"score": judgment.score, "status": judgment.status,
            "evidence_refs": judgment.evidence_refs,
            "findings": [claim.model_dump() for claim in judgment.claims],
            "provenance": provenance, "token_usage": usage, "cost": cost}


if __name__ == "__main__":
    main()
