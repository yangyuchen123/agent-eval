"""GDPVal case-package tests — no LLM, no network."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "gdpval"))

import pytest  # noqa: E402

from agenteval import LLMBackend, Case  # noqa: E402
from agenteval.rubrics import Rubric  # noqa: E402
from skills import (ArtifactPresenceSkill, GDPValJudgeSkill,  # noqa: E402
                    rubric_from_task)


def fake_task() -> dict:
    return {
        "task_id": "83d10b06-xxxx",
        "occupation": "Accountants and Auditors",
        "sector": "Professional",
        "prompt": "produce a workbook",
        "deliverable_files": ["deliverable_files/abc/Sample v2.xlsx"],
        "rubric_items": [
            {"criterion": "is an Excel workbook named Sample",
             "score": 2, "rubric_item_id": "r1"},
            {"criterion": "has a worksheet named exactly 'Sample Size Calculation'",
             "score": 2, "rubric_item_id": "r2"},
            {"criterion": "must NOT contain external links",   # penalty item
             "score": -1, "rubric_item_id": "r3"},
        ],
    }


def fake_backend():
    return LLMBackend(base_url="http://localhost:9/v1", model="fake",
                      api_key="x", timeout=1)


def test_rubric_from_task():
    r = rubric_from_task(fake_task())
    assert isinstance(r, Rubric)
    assert len(r.questions) == 3
    weights = [q.weight for q in r.questions]
    assert weights == [2.0, 2.0, -1.0]        # negative = penalty
    assert r.allowed_scores == (0.0, 1.0)


def test_gdpval_aggregate_is_weighted_sum():
    skill = GDPValJudgeSkill(fake_backend(), fake_task())
    # satisfy items 1,3 (penalty applies); skip item 2
    score = skill.aggregate({"I00": 1.0, "I01": 0.0, "I02": 1.0})
    assert score == pytest.approx(2.0 - 1.0)   # 2*1 + 2*0 + (-1)*1
    # all satisfied
    assert skill.aggregate({"I00": 1.0, "I01": 1.0, "I02": 1.0}) == pytest.approx(3.0)


def test_gdpval_parse_flat_and_aggregate():
    skill = GDPValJudgeSkill(fake_backend(), fake_task())
    parsed = {
        "answers": {
            "I00": {"score": 1.0, "evidence": "workbook", "reason": "ok"},
            "I01": {"score": 0.0, "evidence": "", "reason": "no"},
            "I02": {"score": 1.0, "evidence": "links", "reason": "ok"},
        },
        "summary": "x",
    }
    out = "produced workbook with links"
    result = skill.parse(parsed, Case(case_id="c", task="t"), out)
    assert result.score == pytest.approx(1.0)   # 2 - 1
    assert result.subscores["I00"] == 1.0


def test_artifact_presence():
    s = ArtifactPresenceSkill()
    case = Case(case_id="c", task="t",
                expected={"deliverable_files":
                          ["deliverable_files/abc/Sample v2.xlsx"]})
    ok = s.evaluate(case, "I generated Sample v2.xlsx with the population data")
    assert ok.score == 1.0
    bad = s.evaluate(case, "Here is my analysis in text form.")
    assert bad.score == 0.0
