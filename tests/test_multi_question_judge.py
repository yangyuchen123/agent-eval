import pytest

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


class OffAnchorJudge:
    def evaluate(self, request):
        return JudgeResponse(score=0.7, confidence=0.8)


def test_multi_question_judge_rejects_continuous_score_for_structured_anchors():
    skill = MultiQuestionJudgeSkill(OffAnchorJudge(), {
        "allowed_scores": [0, 0.5, 1],
        "questions": [{
            "id": "q1", "question": "one",
            "score_anchors": [
                {"score": 0, "description": "no"},
                {"score": 0.5, "description": "partial"},
                {"score": 1, "description": "yes"},
            ],
        }],
    })
    with pytest.raises(ValueError, match="declared anchors"):
        skill.evaluate(Case("c", "task"), "output")


def test_multi_question_judge_propagates_allowed_scores_to_each_question():
    client = FakeMultiJudge()
    skill = MultiQuestionJudgeSkill(client, {
        "allowed_scores": [0, 0.5, 1],
        "questions": [
            {"id": "q1", "question": "one", "weight": 2},
            {"id": "q2", "question": "two", "weight": 1},
        ],
    })
    skill.evaluate(Case("c", "task"), "output")
    assert client.requests[0].rubric_question["allowed_scores"] == [0.0, 0.5, 1.0]


def test_multi_question_judge_records_rubric_and_model_provenance():
    class ProvenanceJudge:
        def evaluate(self, request):
            return JudgeResponse(
                score=1.0, confidence=1.0,
                provenance={"model": "judge-model"}, status="scored")
    skill = MultiQuestionJudgeSkill(ProvenanceJudge(), {
        "rubric_id": "r", "version": "v1", "allowed_scores": [0, 1],
        "questions": [{
            "id": "q", "question": "q", "weight": 1,
            "score_anchors": [
                {"score": 0, "description": "no"},
                {"score": 1, "description": "yes"},
            ],
        }],
    })
    result = skill.evaluate(Case("c", "task"), "out")
    assert result.diagnostics["judge"] == {
        "model": "judge-model", "rubric_id": "r", "rubric_version": "v1",
        "evaluator_version": "agenteval.multi-question-judge.v1",
    }
