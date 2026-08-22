"""Run manifest + capability taxonomy tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from agenteval import (CapabilityStore, DEFAULT_TAXONOMY,  # noqa: E402
                       EvaluationRun, build_manifest, evaluator_snapshot,
                       write_manifest, load_manifest)
from agenteval.history import EvalRecord, HistoryStore  # noqa: E402
from agenteval.runner import RunConfig, run_eval  # noqa: E402
from agenteval import Case, Plan, RuleRouter, SkillRegistry  # noqa: E402
from agenteval.skills.base import RuleSkill  # noqa: E402


def test_taxonomy_load_and_tree(tmp_path):
    path = tmp_path / "taxonomy.json"
    import json
    path.write_text(json.dumps(DEFAULT_TAXONOMY), encoding="utf-8")
    store = CapabilityStore(path)
    caps = store.load()
    assert "code_reasoning" in caps
    assert caps["code_reasoning"].parent == "software_engineering"
    assert "root_cause_analysis" in store.children(caps, "code_reasoning")
    tree = store.tree(caps)
    assert "software_engineering" in tree
    assert "code_reasoning" in tree["software_engineering"]["children"]


def test_taxonomy_validation():
    import json
    bad = {"capabilities": [
        {"id": "a", "parent": None, "description": "x"},
        {"id": "b", "parent": "does_not_exist", "description": "y"},
    ]}
    path = Path("/tmp/agenteval_bad_taxonomy.json")
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError):
        CapabilityStore(path).load()
    path.unlink(missing_ok=True)


def test_validate_question_tags():
    import json
    path = Path("/tmp/agenteval_tax.json")
    path.write_text(json.dumps(DEFAULT_TAXONOMY), encoding="utf-8")
    caps = CapabilityStore(path).load()
    unknown = CapabilityStore(path).validate_question_tags(
        caps, {"skill": {"Q1": ("code_reasoning", "made_up")}})
    assert unknown == ["skill.Q1:made_up"]
    path.unlink(missing_ok=True)


def test_evaluator_snapshot_from_records():
    recs = [
        EvalRecord(run_id="r", model_id="m", case_id="c", skill_id="s",
                   score=0.5, rubric_id="patch_quality",
                   rubric_version="2.0.0", evaluator_version="1",
                   judge="deepseek-v4-flash"),
        EvalRecord(run_id="r", model_id="m", case_id="c2", skill_id="s",
                   score=0.5, rubric_id="patch_quality",
                   rubric_version="2.1.0", evaluator_version="1",
                   judge="deepseek-v4-flash"),
    ]
    snap = evaluator_snapshot(recs)
    assert snap["rubric_versions"]["patch_quality"] == ["2.0.0", "2.1.0"]
    assert snap["judge_models"] == ["deepseek-v4-flash"]


def test_manifest_roundtrip(tmp_path):
    run = EvaluationRun(
        run_id="run-x",
        agent={"name": "pi", "version": "1.0"},
        environment={"date_utc": "2026-01-01", "machine": "box"},
        benchmarks=("swebench",),
        evaluator_snapshot={"judge_models": ["j"]},
    )
    path = write_manifest(tmp_path, run)
    assert load_manifest(tmp_path) == run
    assert path.is_file()


def test_run_eval_writes_manifest(tmp_path):
    class S(RuleSkill):
        skill_id = "s"
        role = "core"
        question = "q?"
        definition_version = "t.v1"

        def evaluate(self, case: Case, output: str):
            from agenteval import SkillResult
            return SkillResult(skill_id=self.skill_id, status="ok", score=1.0)

    reg = SkillRegistry()
    reg.register(S())

    def route(case, catalog):
        return Plan(case_id=case.case_id,
                    selected_skills=({"skill_id": "s", "role": "core",
                                      "reason": "r", "parameters": {}},),
                    skipped_skills=())

    config = RunConfig(router=RuleRouter(route), registry=reg,
                       run_root=tmp_path / "run", model_id="m",
                       agent_name="pi", agent_version="0.1",
                       benchmarks=("swebench",))
    run_eval(config, [Case(case_id="c1", task="t")], {"c1": "x"})
    manifest = load_manifest(tmp_path / "run")
    assert manifest.agent == {"name": "pi", "version": "0.1"}
    assert manifest.benchmarks == ("swebench",)
    assert "date_utc" in manifest.environment
    assert "rubric_versions" in manifest.evaluator_snapshot
