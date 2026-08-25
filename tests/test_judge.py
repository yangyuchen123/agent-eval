from agenteval import Case, JudgeClientSkill, JudgeRequest, JudgeResponse


class FakeJudge:
    def __init__(self):
        self.request = None

    def evaluate(self, request):
        self.request = request
        return JudgeResponse(
            score=0.8,
            subscores={"decomposition": 0.9},
            reasons={"decomposition": "supported"},
            confidence=0.7,
            evidence_refs=["trace.jsonl:3"],
            provenance={"judge": "fake"},
        )


def test_judge_client_skill_is_thin_boundary():
    client = FakeJudge()
    case = Case(
        case_id="c1",
        task="decompose",
        context={"trace_ref": "attempt://a1", "artifact_ref": "artifact://a1"},
        metadata={"env_name": "env"},
    )
    result = JudgeClientSkill(client, rubric={"rubric_id": "r1"}).evaluate(case, "output")
    assert result.score == 0.8
    assert result.status == "scored"
    assert client.request.trace_ref == "attempt://a1"
    assert client.request.artifact_ref == "artifact://a1"
    assert client.request.rubric == {"rubric_id": "r1"}
    assert result.evidence["evidence_refs"] == ["trace.jsonl:3"]


def test_judge_request_round_trips_contract():
    case = Case(case_id="c1", task="x")
    request = JudgeRequest(case, {"id": "r"}, "out", trace_ref="t")
    payload = request.to_dict()
    assert payload["schema_version"] == "agenteval.judge_request.v1"
    assert payload["trace_ref"] == "t"


def test_judge_response_rejects_invalid_score():
    try:
        JudgeResponse.from_dict({"score": 2})
    except ValueError as exc:
        assert "score" in str(exc)
    else:
        raise AssertionError("invalid score must be rejected")



def test_http_judge_client_uses_versioned_request(monkeypatch):
    import io
    from agenteval import HttpJudgeClient
    import agenteval.judge as judge_mod

    seen = {}

    class Response:
        status = 200
        def read(self):
            return b'{"score": 0.6, "subscores": {"q": 0.6}, "reasons": {"q": "ok"}, "evidence_refs": ["trace:1"]}'
        def __enter__(self): return self
        def __exit__(self, *args): return None

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = request.data
        seen["auth"] = request.headers.get("Authorization")
        return Response()

    monkeypatch.setattr(judge_mod.urllib.request, "urlopen", fake_urlopen)
    client = HttpJudgeClient("http://judge", api_key="test-key")
    result = client.evaluate(JudgeRequest(Case("c", "task"), {"id": "r"}, "out"))
    assert result.score == 0.6
    assert seen["url"] == "http://judge/v1/judge/evaluate"
    assert seen["auth"] == "Bearer test-key"
    assert b"agenteval.judge_request.v1" in seen["body"]
