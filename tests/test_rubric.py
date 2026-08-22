"""Rubric data-model tests — no LLM, no network."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from agenteval import Case, Rubric, RubricQuestion, RubricStore  # noqa: E402
from agenteval.rubrics import (evidence_in_patch, normalize_patch,  # noqa: E402
                               normalize_whitespace)
from agenteval.skills.rubric import FineGrainedRubric  # noqa: E402
from agenteval.protocols import SkillResult  # noqa: E402


def make_rubric() -> Rubric:
    return Rubric(
        rubric_id="test_rubric",
        version="1.0.0",
        description="test",
        questions=(
            RubricQuestion(id="Q1", question="q1?", anchors="1=good; 0=bad",
                           evidence="quote", weight=0.7),
            RubricQuestion(id="Q2", question="q2?", anchors="1=good; 0=bad",
                           evidence="quote"),
        ),
        meta_questions=frozenset({"Q2"}),
    )


def make_skill(rubric: Rubric | None = None):
    from agenteval import LLMBackend
    backend = LLMBackend(base_url="http://localhost:9/v1", model="fake",
                         api_key="x", timeout=1)
    return FineGrainedRubric(backend, rubric or make_rubric())


# ------------------------------------------------------------ model -------

def test_rubric_roundtrip(tmp_path):
    store = RubricStore(tmp_path)
    r = make_rubric()
    path = store.save(r)
    loaded = store.load("test_rubric")
    assert loaded == r
    assert path.is_file()
    assert store.list_rubrics() == ["test_rubric"]


def test_rubric_validation():
    with pytest.raises(ValueError):
        Rubric.from_dict({"rubric_id": "x", "version": "1"})   # no questions
    with pytest.raises(ValueError):
        RubricQuestion.from_dict({"id": "Q1"})                 # no question


def test_rubric_version_in_definition():
    skill = make_skill()
    assert skill.definition_version.endswith("rubric.v1.0.0")


# ------------------------------------------------------------ parsing -----

def test_parse_scores_and_meta_evidence():
    skill = make_skill()
    parsed = {
        "answers": {
            "Q1": {"score": 0.75, "evidence": "+ s = x",
                   "reason": "ok"},
            "Q2": {"score": 1.0, "evidence": "summary text not in patch",
                   "reason": "meta exempt"},
        },
        "summary": "fine",
    }
    out = "diff --git a/f.py b/f.py\n+ s = x\n"
    result = skill.parse(parsed, Case(case_id="c", task="t"), out)
    assert result.score == pytest.approx((0.75 * 0.7 + 1.0 * 1.0) / 1.7, rel=1e-3)
    assert result.subscores["Q1"] == 0.75
    assert result.subscores["Q2"] == 1.0
    # Q2 is meta → evidence kept even though not in patch
    assert result.evidence["per_question"]["Q2"] != ""


def test_parse_rejects_fabricated_evidence():
    skill = make_skill()
    parsed = {
        "answers": {
            "Q1": {"score": 1.0, "evidence": "THIS DOES NOT EXIST ANYWHERE",
                   "reason": "made up"},
            "Q2": {"score": 0.5, "evidence": "x", "reason": "r"},
        },
    }
    out = "diff --git a/f.py b/f.py\n+ real line\n"
    result = skill.parse(parsed, Case(case_id="c", task="t"), out)
    assert "Q1" in result.evidence["fabricated_evidence_rejected"]
    assert result.evidence["per_question"]["Q1"] == ""


def test_parse_discrete_ladder_snapping():
    skill = make_skill()
    parsed = {"answers": {"Q1": {"score": 0.4, "evidence": "x",
                                 "reason": "r"},
                          "Q2": {"score": 0.9, "evidence": "y",
                                 "reason": "r"}}}
    out = "x\ny\n"
    result = skill.parse(parsed, Case(case_id="c", task="t"), out)
    # 0.4 → snaps to 0.5; 0.9 → snaps to 1.0
    assert result.subscores["Q1"] == 0.5
    assert result.subscores["Q2"] == 1.0


# ------------------------------------------------------- evidence utils ---

def test_evidence_in_patch_utils():
    patch = ("diff --git a/sympy/x.py b/sympy/x.py\n"
             "+            s = domain.generators[gens.index(r[i])]\n"
             "-            while i < len(r):\n"
             "-                i += abs(power)\n")
    norm = normalize_patch(patch)
    assert "sympy/x.py" in norm
    assert evidence_in_patch("s = domain.generators[gens.index(r[i])]", norm)
    # ellipsis allowed
    assert evidence_in_patch("while i < len(r): ... i += abs(power)", norm)
    # fabricated quote rejected
    assert not evidence_in_patch("this is not in the patch", norm)


def test_aggregate_skips_invalid():
    skill = make_skill()
    result = skill.aggregate({"Q1": None, "Q2": 0.5})
    assert result == pytest.approx(0.5)
