"""Preference and rubric-planner data contracts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenteval import (
    Case,
    LLMBackend,
    MetaPrinciple,
    MetaRubric,
    PreferenceExample,
    PreferenceStore,
    RubricPlanner,
)


def example() -> PreferenceExample:
    return PreferenceExample(
        example_id="pref-1",
        case={"task": "answer"},
        candidates=(
            {"id": "a", "output": "grounded"},
            {"id": "b", "output": "invented"},
        ),
        preferred="a",
        rejected="b",
        human_reason=("does not invent facts",),
        dimensions=("evidence_boundedness",),
    )


def test_preference_example_roundtrip_and_store(tmp_path: Path):
    path = tmp_path / "examples.json"
    path.write_text(json.dumps({"examples": [example().to_dict()]}), encoding="utf-8")
    loaded = PreferenceStore(path).load()
    assert loaded == [example()]
    with pytest.raises(ValueError):
        PreferenceExample("bad", {}, ({"id": "a"},), "a")


def test_planner_infers_and_instantiates_structured_rubric(monkeypatch):
    backend = LLMBackend(base_url="http://judge", model="judge")
    responses = [
        {"parsed": {"rubric_id": "human", "version": "1", "description": "d", "principles": [
            {"id": "evidence_boundedness", "name": "Evidence", "description": "No unsupported facts", "source_examples": ["pref-1"]}
        ], "source_examples": ["pref-1"]}, "response_metadata": {}},
        {"parsed": {"rubric_id": "case-rubric", "version": "1", "description": "case", "questions": [
            {"id": "groundedness", "question": "Is it grounded?", "anchors": "1 good; 0.5 partial; 0 bad", "score_anchors": [{"score": 0, "description": "unsupported"}, {"score": 0.5, "description": "partially supported"}, {"score": 1, "description": "fully supported"}], "evidence": "trace/artifact", "weight": 1, "lineage": ["evidence_boundedness"], "source_principles": ["evidence_boundedness"], "case_adaptation": "apply to this task"}
        ], "source_examples": ["pref-1"]}, "response_metadata": {}},
    ]
    monkeypatch.setattr(backend, "infer", lambda messages: responses.pop(0))
    planner = RubricPlanner(backend)
    meta = planner.infer_meta_rubric([example()])
    rubric = planner.instantiate(meta, Case(case_id="c", task="new task"))
    assert meta.principles[0].principle_id == "evidence_boundedness"
    assert rubric.questions[0].source_principles == ("evidence_boundedness",)
    assert [anchor.score for anchor in rubric.questions[0].score_anchors] == [0.0, 0.5, 1.0]
    assert rubric.provenance["source_meta_rubric"] == "human"


def test_planner_does_not_serialize_octagon_runtime_payload():
    backend = LLMBackend(base_url="http://judge", model="judge")
    planner = RubricPlanner(backend)
    case = Case(
        case_id="octagon",
        task="Do the task",
        context={
            "_eval_sample": {"trace": ["x"] * 10000},
            "trace": ["x"] * 10000,
            "events": ["y"] * 10000,
            "workspace_root": "/private/workspace",
            "requirements": ["keep this"],
        },
    )
    meta = MetaRubric("m", "1", "d", (MetaPrinciple("p", "P", "d"),))
    messages = planner._instantiate_messages(meta, case)
    assert len(messages[-1]["content"]) < 20_000
    assert "_eval_sample" not in messages[-1]["content"]
    assert "requirements" in messages[-1]["content"]
