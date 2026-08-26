import httpx
import pytest
from pydantic_ai.models.test import TestModel

from agentjudge.server import create_app


@pytest.mark.anyio
async def test_http_service_returns_judgment_and_provenance():
    model = TestModel(custom_output_args={
        "question_id": "q1", "score": 0.75, "confidence": 0.8,
        "claims": [], "evidence_refs": [], "missing_evidence": [],
        "contradictions": [], "status": "unverified",
    })
    app = create_app(model=model, evidence_factory=lambda request: __import__(
        "agentjudge.evidence", fromlist=["InMemoryEvidenceProvider"]
    ).InMemoryEvidenceProvider([]))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/judge/evaluate", json={
            "schema_version": "agenteval.judge_request.v1",
            "case": {"case_id": "c1", "task": "x"},
            "rubric": {"rubric_id": "r1"},
            "rubric_question": {"id": "q1", "question": "x"},
            "agent_output": "out",
        })
    assert response.status_code == 200
    body = response.json()
    assert body["score"] == 0.75
    assert body["provenance"]["query_trajectory"]
    assert body["provenance"]["query_trajectory"][0]["operation"] == "search"
    assert body["provenance"]["evidence_manifest"]["record_count"] == 0
    assert body["provenance"]["scoring"]["scoring_mode"] == "continuous_legacy"


@pytest.mark.anyio
async def test_health_endpoint():
    app = create_app(model=TestModel())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.json()["status"] == "ok"


@pytest.mark.anyio
async def test_http_service_records_selected_discrete_anchor():
    model = TestModel(custom_output_args={
        "question_id": "q1", "score": 0.5, "confidence": 0.8,
        "claims": [], "evidence_refs": [], "missing_evidence": [],
        "contradictions": [], "status": "partially_supported",
    })
    app = create_app(model=model, evidence_factory=lambda request: __import__(
        "agentjudge.evidence", fromlist=["InMemoryEvidenceProvider"]
    ).InMemoryEvidenceProvider([]))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/judge/evaluate", json={
            "schema_version": "agenteval.judge_request.v1",
            "case": {"case_id": "c1", "task": "x"},
            "rubric": {"rubric_id": "r1"},
            "rubric_question": {
                "id": "q1", "question": "x",
                "score_anchors": [
                    {"score": 0.0, "description": "no"},
                    {"score": 0.5, "description": "partial"},
                    {"score": 1.0, "description": "yes"},
                ],
            },
            "agent_output": "out",
        })
    assert response.status_code == 200
    scoring = response.json()["provenance"]["scoring"]
    assert scoring["scoring_mode"] == "discrete_anchor"
    assert scoring["selected_anchor"]["score"] == 0.5
