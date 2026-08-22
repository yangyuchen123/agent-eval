"""Framework self-tests — run without any LLM or network."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from agenteval import (Case, Plan, RuleRouter, SkillRegistry,  # noqa: E402
                       weighted_case_score)
from agenteval.planner import LLMRouter, validate_plan  # noqa: E402
from agenteval.protocols import SkillResult  # noqa: E402
from agenteval.runner import (RunConfig, run_eval,  # noqa: E402
                              write_evidence)
from agenteval.skills.base import RuleSkill  # noqa: E402


# ------------------------------------------------------------- fixtures --

class AnswerSkill(RuleSkill):
    skill_id = "answer"
    role = "core"
    question = "answer matches?"
    definition_version = "test.answer.v1"

    def evaluate(self, case: Case, output: str) -> SkillResult:
        text = output.strip()
        if text.startswith("A:"):
            text = text[2:].strip()
        ok = text == case.expected.get("answer")
        return SkillResult(skill_id=self.skill_id, status="ok",
                           score=1.0 if ok else 0.0,
                           subscores={"match": 1.0 if ok else 0.0},
                           reasons={"match": "ok" if ok else "no"})


class FormatSkill(RuleSkill):
    skill_id = "format"
    role = "observation"
    question = "has prefix?"
    definition_version = "test.format.v1"

    def evaluate(self, case: Case, output: str) -> SkillResult:
        ok = output.startswith("A:")
        return SkillResult(skill_id=self.skill_id, status="ok",
                           score=1.0 if ok else 0.0,
                           subscores={"prefix": 1.0 if ok else 0.0},
                           reasons={"prefix": "ok" if ok else "no"})


class BrokenSkill(RuleSkill):
    skill_id = "broken"
    role = "diagnostic"
    question = "always crashes?"
    definition_version = "test.broken.v1"

    def evaluate(self, case: Case, output: str) -> SkillResult:
        raise RuntimeError("boom")


def make_registry() -> SkillRegistry:
    r = SkillRegistry()
    r.register(AnswerSkill())
    r.register(FormatSkill())
    return r


def make_cases():
    return [
        Case(case_id="c1", task="1+1", expected={"answer": "2"}, context={}),
        Case(case_id="c2", task="2+2", expected={"answer": "4"}, context={}),
    ]


def route_all(case: Case, catalog: list[dict]) -> Plan:
    return Plan(
        case_id=case.case_id,
        selected_skills=(
            {"skill_id": "answer", "role": "core",
             "reason": "answers must match", "parameters": {}},
            {"skill_id": "format", "role": "observation",
             "reason": "format must hold", "parameters": {}},
        ),
        skipped_skills=(),
    )


# -------------------------------------------------------------- planner --

def test_validate_plan_ok():
    catalog = [s.spec().to_dict() for s in make_registry().skills.values()]
    plan = validate_plan(route_all(make_cases()[0], catalog), catalog)
    assert plan.selected_ids == ("answer", "format")
    assert plan.selected_skills[0]["role"] == "core"


def test_validate_plan_rejects_bad():
    catalog = [s.spec().to_dict() for s in make_registry().skills.values()]
    bad = Plan(case_id="c1",
               selected_skills=({"skill_id": "nope", "role": "core", "reason": "x",
                                 "parameters": {}},),
               skipped_skills=())
    with pytest.raises(ValueError):
        validate_plan(bad, catalog)


def test_validate_plan_requires_core():
    catalog = [s.spec().to_dict() for s in make_registry().skills.values()]
    no_core = Plan(case_id="c1",
                   selected_skills=({"skill_id": "format", "role": "observation",
                                     "reason": "x", "parameters": {}},),
                   skipped_skills=())
    with pytest.raises(ValueError):
        validate_plan(no_core, catalog)


# --------------------------------------------------------------- runner --

def test_run_eval_and_cache(tmp_path):
    registry = make_registry()
    config = RunConfig(router=RuleRouter(route_all), registry=registry,
                       run_root=tmp_path / "run", plan_root=tmp_path / "plans")
    cases = make_cases()
    outputs = {"c1": "A: 2", "c2": "A: 5"}

    report = run_eval(config, cases, outputs)
    assert set(report.evidence) == {"c1", "c2"}
    assert report.evidence["c1"].skill_results["answer"].score == 1.0
    assert report.evidence["c2"].skill_results["answer"].score == 0.0

    # cache: second run should reuse results (skill_hits == 2)
    report2 = run_eval(config, cases, outputs)
    assert report2.cache_stats.get("skill_hits", 0) == 4  # 2 cases × 2 skills, all cached

    # evidence written to disk
    root = write_evidence(config.run_root, report)
    assert (root / "c1.json").is_file()


def test_run_eval_isolates_skill_failures(tmp_path):
    registry = make_registry()
    registry.register(BrokenSkill())

    def route(case, catalog):
        return Plan(case_id=case.case_id,
                    selected_skills=(
                        {"skill_id": "answer", "role": "core",
                         "reason": "core", "parameters": {}},
                        {"skill_id": "format", "role": "observation",
                         "reason": "obs", "parameters": {}},
                        {"skill_id": "broken", "role": "diagnostic",
                         "reason": "x", "parameters": {}},
                    ),
                    skipped_skills=())

    config = RunConfig(router=RuleRouter(route), registry=registry,
                       run_root=tmp_path / "run")
    report = run_eval(config, make_cases(), {"c1": "x"})
    result = report.evidence["c1"].skill_results["broken"]
    assert result.status == "error"
    assert result.score is None
    assert "boom" in result.diagnostics["error"]


def test_missing_output_reported(tmp_path):
    registry = make_registry()
    config = RunConfig(router=RuleRouter(route_all), registry=registry,
                       run_root=tmp_path / "run")
    report = run_eval(config, make_cases(), {"c1": "A: 2"})
    assert len(report.failures) == 1
    assert report.failures[0]["case_id"] == "c2"


# --------------------------------------------------------------- score ---

def test_weighted_case_score_and_gate(tmp_path):
    registry = make_registry()
    cases = make_cases()
    outputs = {"c1": "A: 2"}
    config = RunConfig(router=RuleRouter(route_all), registry=registry,
                       run_root=tmp_path / "score_run")
    report = run_eval(config, cases, outputs)
    ev = report.evidence["c1"]
    weights = {"answer": 0.7, "format": 0.3}
    assert weighted_case_score(ev, weights) == pytest.approx(1.0)

    # gate: pretend format is the gate and it fails → case score zeroed
    ev2 = report.evidence["c1"]
    assert weighted_case_score(ev2, weights, gate_skill="format",
                               gate_threshold=0.5) == 1.0


# ------------------------------------------------------------ backends ---

def test_backend_json_parsing():
    from agenteval.backends import _parse_json
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json('prefix {"a": 1} suffix') == {"a": 1}
    with pytest.raises(Exception):
        _parse_json("not json")
