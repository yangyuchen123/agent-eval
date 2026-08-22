"""Evaluation-history tests — no LLM, no network."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from agenteval import (Case, CaseEvidence, EvalRecord, HistoryStore,  # noqa: E402
                       Plan, SkillResult, new_run_id, question_stats,
                       rubric_question_report, summary_by_skill)
from agenteval.history import by_rubric, by_skill, record_from_evidence  # noqa: E402
from agenteval.runner import RunConfig, run_eval  # noqa: E402
from agenteval.skills.base import RuleSkill  # noqa: E402


def make_evidence(case_id: str, subscores: dict) -> CaseEvidence:
    return CaseEvidence(
        case_id=case_id,
        case={"case_id": case_id, "task": "t"},
        output="out",
        plan=Plan(case_id=case_id, selected_skills=(), skipped_skills=()),
        skill_results={
            "quality": SkillResult(skill_id="quality", status="ok",
                                   score=sum(subscores.values()) / len(subscores),
                                   subscores=subscores,
                                   diagnostics={"judge": {
                                       "rubric_id": "patch_quality",
                                       "rubric_version": "2.0.0",
                                       "model": "deepseek-v4-flash"}}),
        },
    )


def test_record_from_evidence_carries_rubric_meta():
    ev = make_evidence("c1", {"Q1": 1.0, "Q2": 0.5})
    recs = record_from_evidence(ev, run_id="r1", model_id="gold")
    assert len(recs) == 1
    rec = recs[0]
    assert rec.rubric_id == "patch_quality"
    assert rec.rubric_version == "2.0.0"
    assert rec.judge == "deepseek-v4-flash"
    assert rec.score == pytest.approx(0.75)


def test_history_append_and_load_roundtrip(tmp_path):
    store = HistoryStore(tmp_path / "history.jsonl")
    ev1 = make_evidence("c1", {"Q1": 1.0, "Q2": 0.5})
    ev2 = make_evidence("c2", {"Q1": 0.75, "Q2": 0.75})
    store.append(record_from_evidence(ev1, run_id="r1", model_id="m1"))
    store.append(record_from_evidence(ev2, run_id="r1", model_id="m1"))
    loaded = store.load()
    assert len(loaded) == 2
    assert loaded[0].case_id == "c1"
    assert loaded[1].subscores["Q2"] == 0.75


def test_queries_and_stats():
    recs = [
        EvalRecord(run_id="r", model_id="m", case_id=f"c{i}",
                   skill_id="quality", score=0.8, subscores={"Q1": 0.8},
                   rubric_id="patch_quality", rubric_version="2.0.0")
        for i in range(3)
    ]
    assert len(by_skill(recs, "quality")) == 3
    assert len(by_rubric(recs, "patch_quality", "2.0.0")) == 3
    assert question_stats(recs, "Q1")["mean"] == pytest.approx(0.8)

    low_var = [EvalRecord(run_id="r", model_id="m", case_id=f"c{i}",
                          skill_id="q", score=0.8, subscores={"Q2": 0.8},
                          rubric_id="patch_quality")
               for i in range(3)]
    rep = rubric_question_report(low_var, "patch_quality")
    assert rep["n_low_discrimination"] == 1          # Q2 all identical
    assert rep["questions"]["Q2"]["discriminates"] is False


def test_summary_by_skill():
    recs = [
        EvalRecord(run_id="r", model_id="m", case_id="c1", skill_id="a",
                   score=0.5, subscores={}),
        EvalRecord(run_id="r", model_id="m", case_id="c2", skill_id="a",
                   score=0.7, subscores={}),
    ]
    s = summary_by_skill(recs)
    assert s["a"]["mean"] == pytest.approx(0.6)


def test_run_eval_writes_history(tmp_path):
    from agenteval import Plan, RuleRouter, SkillRegistry

    class S(RuleSkill):
        skill_id = "s"
        role = "core"
        question = "q?"
        definition_version = "t.v1"

        def evaluate(self, case: Case, output: str) -> SkillResult:
            return SkillResult(skill_id=self.skill_id, status="ok", score=1.0,
                               subscores={"x": 1.0})

    reg = SkillRegistry()
    reg.register(S())

    def route(case, catalog):
        return Plan(case_id=case.case_id,
                    selected_skills=({"skill_id": "s", "role": "core",
                                      "reason": "r", "parameters": {}},),
                    skipped_skills=())

    config = RunConfig(router=RuleRouter(route), registry=reg,
                       run_root=tmp_path / "run", model_id="test")
    run_eval(config, [Case(case_id="c1", task="t")], {"c1": "x"})
    recs = HistoryStore(config.history_path).load()
    assert len(recs) == 1
    assert recs[0].model_id == "test"
    assert recs[0].skill_id == "s"
