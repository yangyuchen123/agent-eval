import pytest
from pydantic_ai.models.test import TestModel

from agentjudge.baselines import FullTraceJudgeService, StaticRetrievalJudgeService
from agentjudge.evidence import InMemoryEvidenceProvider
from agentjudge.models import EvidenceRecord, JudgeRequest


def record(evidence_id="E1"):
    return EvidenceRecord(evidence_id=evidence_id, source="trace.jsonl", event_type="tool_result",
                          evidence_class="direct_runtime_event", claim_strength="direct",
                          content={"description": "validation passed"})


def request():
    return JudgeRequest(case={"task": "validate"}, rubric={},
                        rubric_question={"id": "q1", "question": "Was validation performed?",
                                         "evidence": "validation result"}, agent_output="")


@pytest.mark.anyio
async def test_full_trace_baseline_has_no_retrieval_actions():
    model = TestModel(custom_output_args={"question_id":"q1","score":1,"confidence":1,
        "claims":[],"evidence_refs":["E1"],"missing_evidence":[],"contradictions":[],"status":"supported"})
    service = FullTraceJudgeService(model)
    result = await service.evaluate(request(), [record()])
    assert result.score == 1
    assert service.last_provenance["record_count"] == 1
    assert service.last_provenance["retrieval_actions"] == []


@pytest.mark.anyio
async def test_static_retrieval_baseline_records_selected_ids():
    model = TestModel(custom_output_args={"question_id":"q1","score":1,"confidence":1,
        "claims":[],"evidence_refs":["E1"],"missing_evidence":[],"contradictions":[],"status":"supported"})
    provider = InMemoryEvidenceProvider([record(), record("E2")])
    service = StaticRetrievalJudgeService(model, top_k=1)
    await service.evaluate(request(), provider)
    assert service.last_provenance["record_count"] == 1
    assert service.last_provenance["retrieval_actions"][0]["operation"] == "static_search"


@pytest.mark.anyio
async def test_full_trace_baseline_records_selected_anchor():
    anchored = JudgeRequest(
        case={"task": "validate"}, rubric={}, agent_output="",
        rubric_question={
            "id": "q1", "question": "Was validation performed?",
            "score_anchors": [
                {"score": 0.0, "description": "no"},
                {"score": 0.5, "description": "partial"},
                {"score": 1.0, "description": "yes"},
            ],
        },
    )
    model = TestModel(custom_output_args={"question_id":"q1","score":0.5,"confidence":1,
        "claims":[],"evidence_refs":["E1"],"missing_evidence":[],"contradictions":[],"status":"partially_supported"})
    service = FullTraceJudgeService(model)
    await service.evaluate(anchored, [record()])
    assert service.last_provenance["scoring"]["selected_anchor"]["score"] == 0.5
