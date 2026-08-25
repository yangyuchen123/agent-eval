from agenteval import Case, JudgeResponse, MultiQuestionJudgeSkill


class FakeMultiJudge:
    def __init__(self):
        self.requests = []

    def evaluate(self, request):
        self.requests.append(request)
        qid = request.rubric_question["id"]
        score = {"q1": 1.0, "q2": 0.5}[qid]
        return JudgeResponse(score=score, confidence=0.8, evidence_refs=[f"trace:{qid}"])


def test_multi_question_judge_runs_independent_requests_and_aggregates():
    client = FakeMultiJudge()
    skill = MultiQuestionJudgeSkill(client, {
        "questions": [
            {"id": "q1", "question": "one", "weight": 2},
            {"id": "q2", "question": "two", "weight": 1},
        ]
    })
    result = skill.evaluate(Case("c", "task"), "output")
    assert result.score == 0.833333
    assert result.subscores == {"q1": 1.0, "q2": 0.5}
    assert [r.rubric_question["id"] for r in client.requests] == ["q1", "q2"]
    assert result.evidence["evidence_refs"] == ["trace:q1", "trace:q2"]
    assert result.diagnostics["question_count"] == 2
