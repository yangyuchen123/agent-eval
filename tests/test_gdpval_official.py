from pathlib import Path

import pytest

from agenteval.gdpval_official import (
    load_official_criteria,
    official_questions_for_b_judge,
    proxy_gold_labels,
    unweighted_mean,
    weighted_overall,
    weights_by_id,
)

OFFICIAL = Path("/home/yang/agent-octagon-envs/gdpval-prepaid-amortization-official/private/official_rubric.json")


def test_official_loader_reads_56_weighted_items():
    criteria = load_official_criteria(OFFICIAL)
    assert len(criteria) == 56
    questions = official_questions_for_b_judge(criteria)
    assert len(questions) == 56
    assert len({q["id"] for q in questions}) == 56
    assert all(q["weight"] == 1.0 for q in questions)
    weights = [q["official_weight"] for q in questions]
    assert sorted(set(weights)) == [1.0, 2.0, 5.0]
    assert sum(weights) == 95.0
    assert questions[0]["question"].startswith("Delivers a single Excel workbook")


def test_empty_official_file_fails(tmp_path: Path):
    path = tmp_path / "empty.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="no official rubric criteria"):
        load_official_criteria(path)


def test_weighted_overall_uses_official_points_not_item_count():
    weights = {"a": 2.0, "b": 1.0, "c": 5.0}
    scores = {"a": 1.0, "b": 0.0, "c": 1.0}
    assert unweighted_mean(scores.values()) == pytest.approx(2 / 3)
    assert weighted_overall(scores, weights) == pytest.approx(7 / 8)


def test_proxy_gold_majority_and_flips():
    weights = {"a": 2.0, "b": 1.0}
    repeats = [
        {"a": 1.0, "b": 0.0},
        {"a": 1.0, "b": 1.0},
        {"a": 1.0, "b": 0.0},
        {"a": 1.0, "b": 0.0},
        {"a": 0.0, "b": 0.0},
    ]
    labels = proxy_gold_labels(repeats, weights)
    assert labels["majority_by_id"] == {"a": 1, "b": 0}
    assert labels["flip_ids"] == ["a", "b"]
    assert labels["unweighted_majority_mean"] == pytest.approx(0.5)
    assert labels["weighted_majority_overall"] == pytest.approx(2 / 3)


def test_b_judge_questions_keep_binary_anchors():
    questions = official_questions_for_b_judge(
        [{"rubric_item_id": "x", "criterion": "Workbook exists.", "score": 2}]
    )
    assert questions[0]["score_anchors"][0]["score"] == 0.0
    assert questions[0]["score_anchors"][1]["score"] == 1.0
    assert weights_by_id(questions) == {"x": 2.0}
