"""Run a real Agentic Evidence Judge meta-evaluation from environment config.

This script intentionally refuses to invent a model result or Gold. It uses
one currently available real attempt as a smoke/calibration candidate; reaching
30-50 cases requires adding more reviewed attempts under meta_eval/gold/.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

from agenteval.meta_eval import EvidenceSnapshot, MetaCase, MetaEvalRunner, reorder, add_distractors, lengthen, remove
from agentjudge.http_service import load_project_dotenv

load_project_dotenv()

ATTEMPT = Path(os.environ.get("META_EVAL_ATTEMPT", "run/launch-readiness-decomposition-v1/attempt")).resolve()
OUTPUT = Path(os.environ.get("META_EVAL_OUTPUT", "run/meta_eval/launch-readiness-real"))


def build_case():
    from agentjudge.catalog import EvidenceCatalog
    catalog = EvidenceCatalog.from_attempt_dir(ATTEMPT)
    records = [record.model_dump() for record in catalog.records]
    trace_digest = hashlib.sha256((ATTEMPT / "trace.jsonl").read_bytes()).hexdigest()
    return MetaCase(
        case_id=os.environ.get("META_EVAL_CASE_ID", "launch-readiness-decomposition-v1"),
        question_id=os.environ.get("META_EVAL_QUESTION_ID", "coordination_and_handoff_quality"),
        case={"case_id": "launch-readiness-decomposition-v1", "task": "Evaluate task decomposition, assignment, handoff, and result recovery."},
        question={"id": "coordination_and_handoff_quality", "question": "How well are work packages assigned, coordinated, and recovered at runtime?", "anchors": "1=strong; 0.5=partial; 0=absent", "evidence": "runtime task assignment and handoff evidence"},
        rubric={"rubric_id": "launch-readiness-manual", "version": "frozen-2026-08-25"},
        agent_output="",
        evidence=EvidenceSnapshot.from_records(records),
        trace_digest=trace_digest,
        judge_config={"model": os.environ.get("JUDGE_MODEL", "gpt-5.6-luna"), "temperature": os.environ.get("JUDGE_TEMPERATURE", "unset")},
    )


def make_agentic_judge():
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from agentjudge.models import JudgeRequest
    from agentjudge.service import QuestionJudgeService
    from agentjudge.catalog import EvidenceCatalog

    key = os.environ.get("JUDGE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("JUDGE_API_KEY/OPENAI_API_KEY is not set; refusing to claim a real LLM run")
    model = OpenAIChatModel(os.environ.get("JUDGE_MODEL", "gpt-5.6-luna"), provider=OpenAIProvider(base_url=os.environ.get("JUDGE_BASE_URL"), api_key=key))

    def judge(case, snapshot):
        async def run():
            from agentjudge.models import EvidenceRecord
            provider = EvidenceCatalog([EvidenceRecord.model_validate(r) for r in snapshot.records])
            request = JudgeRequest(case=case.case, rubric=case.rubric, rubric_question=case.question, agent_output=case.agent_output, trace_ref={"snapshot_digest": snapshot.snapshot_digest}, metadata={"meta_eval": True})
            service = QuestionJudgeService(model, provider)
            judgment = await service.evaluate(request)
            return {"score": judgment.score, "status": judgment.status, "evidence_refs": judgment.evidence_refs, "findings": [c.model_dump() for c in judgment.claims], "provenance": {"query_trajectory": service.last_query_trajectory, "snapshot_digest": snapshot.snapshot_digest}}
        return asyncio.run(run())
    return judge


def main():
    case = build_case()
    judge = make_agentic_judge()
    perturbation_map = {
        "none": ("none", lambda s, _: s),
        "order_shuffle": ("order_shuffle", lambda s, seed: reorder(s, seed)),
        "trace_2x": ("trace_2x", lambda s, seed: lengthen(s, 2, seed=seed)),
        "trace_5x": ("trace_5x", lambda s, seed: lengthen(s, 5, seed=seed)),
    }
    selected = os.environ.get("META_EVAL_PERTURBATIONS", "none,order_shuffle,trace_2x,trace_5x").split(",")
    perturbations = [perturbation_map[name.strip()] for name in selected if name.strip() in perturbation_map]
    result = MetaEvalRunner(OUTPUT).run([case], {"agentic_evidence": judge}, repeats=int(os.environ.get("META_EVAL_REPEATS", "5")), perturbations=perturbations, seed=int(os.environ.get("META_EVAL_SEED", "20260825")))
    print(json.dumps({"output": str(OUTPUT), "manifest": result["manifest"], "metrics": result["metrics"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
