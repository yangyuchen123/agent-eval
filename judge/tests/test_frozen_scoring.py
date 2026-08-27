import pytest
from pydantic_ai.models.test import TestModel

from agentjudge.scoring import FrozenEvidenceScoringService


QUESTION = {
    "id": "observed_failure_handling",
    "question": "Did the agent handle observable failures?",
    "score_anchors": [
        {"score": 0.0, "label": "unsupported", "description": "ignored"},
        {"score": 0.5, "label": "partial", "description": "partly recovered"},
        {"score": 1.0, "label": "supported", "description": "fully recovered"},
    ],
}
BUNDLE = {
    "schema_version": "agenteval.frozen_evidence_bundle.v1",
    "case_id": "case-1",
    "question_id": "observed_failure_handling",
    "facts": [
        {"fact_id": "F1", "evidence_refs": ["trace.jsonl:1"],
         "evidence_class": "direct_runtime_event", "statement": "A command failed."},
        {"fact_id": "F2", "evidence_refs": ["trace.jsonl:2"],
         "evidence_class": "direct_runtime_event", "statement": "A retry succeeded."},
    ],
    "claim_set": [{"claim_id": "C1", "statement": "The failure was recovered."}],
    "missing_facts": [],
    "contradictions": [],
}


@pytest.mark.anyio
async def test_frozen_scoring_has_no_tools_and_records_selected_anchor():
    model = TestModel(custom_output_args={
        "question_id": "observed_failure_handling",
        "score": 1.0,
        "confidence": 0.9,
        "selected_anchor_label": "supported",
        "rationale": "F1 and F2 establish recovery.",
        "fact_ids_used": ["F1", "F2"],
        "fact_ids_not_used": [],
    })
    service = FrozenEvidenceScoringService(model)
    decision = await service.evaluate(question=QUESTION, bundle=BUNDLE)
    assert decision.score == 1.0
    assert service.last_provenance["tools_available"] == []
    assert service.last_provenance["selected_anchor"]["label"] == "supported"
    assert service.last_provenance["fact_ids"] == ["F1", "F2"]


@pytest.mark.anyio
async def test_frozen_scoring_rejects_unknown_fact_ids():
    model = TestModel(custom_output_args={
        "question_id": "observed_failure_handling",
        "score": 1.0,
        "confidence": 0.9,
        "selected_anchor_label": "supported",
        "rationale": "Invented support.",
        "fact_ids_used": ["F999"],
        "fact_ids_not_used": [],
    })
    service = FrozenEvidenceScoringService(model)
    with pytest.raises(Exception, match="Unknown fact_id|maximum output retries"):
        await service.evaluate(question=QUESTION, bundle=BUNDLE)
