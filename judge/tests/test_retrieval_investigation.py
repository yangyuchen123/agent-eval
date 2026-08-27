import pytest
from pydantic_ai.models.test import TestModel

from agentjudge.evidence import InMemoryEvidenceProvider
from agentjudge.investigation import RetrievalInvestigationService
from agentjudge.models import EvidenceRecord


def record(evidence_id="E1"):
    return EvidenceRecord(
        evidence_id=evidence_id, source="trace.jsonl", event_type="tool_result",
        evidence_class="direct_runtime_event", claim_strength="direct",
        tool_call_id="call-1", content={"result": "validation failed"},
    )


@pytest.mark.anyio
async def test_retrieval_only_output_has_no_score_and_records_agent_tool_calls():
    model = TestModel(custom_output_args={
        "question_id": "q1",
        "factual_summary": "A validation failure occurred.",
        "findings": [{"finding_id": "F1", "statement": "Validation failed.",
                      "basis": "observed", "evidence_refs": ["E1"]}],
        "evidence_refs": ["E1"],
        "missing_evidence": ["No recovery result found."],
        "contradictions": [],
        "stop_reason": "Relevant failure was found; no recovery event was available.",
    }, call_tools=["search_evidence"])
    provider = InMemoryEvidenceProvider([record()])
    service = RetrievalInvestigationService(model, provider)
    result = await service.investigate(
        task="Handle validation failures",
        question={"id": "q1", "question": "Was failure handled?", "score_anchors": []},
    )
    assert not hasattr(result, "score")
    assert result.evidence_refs == ["E1"]
    assert service.last_tool_trajectory[0]["operation"] == "search"
    assert service.last_tool_trajectory[0]["result_ids"] == ["E1"]
