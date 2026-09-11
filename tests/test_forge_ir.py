from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenteval import IRRubricProjectionError, Rubric, project_ir_rubric, project_ir_rubric_file

NL_DOCS_IR = Path(
    "/home/yang/benchagent/benchmark-forge/run/nl-docs-edit-20260907/contract/environment-ir.json"
)


def _criterion(criterion_id: str, description: str, *, weight: float = 30.0, evidence=None):
    return {
        "criterion_id": criterion_id,
        "description": description,
        "weight": weight,
        "minimum_score": 0.0,
        "critical_gate": False,
        "evidence_refs": evidence or ["evidence_artifact"],
        "artifact_refs": ["readme"],
        "state_refs": [],
        "self_report_allowed": False,
    }


def _ir(*, frozen=True, checksum="sha256:abc", criteria=None):
    return {
        "schema_version": "benchmark-forge.environment-ir.v1",
        "environment_id": "generated-docs",
        "task_id": "repo_documentation_revision_001",
        "frozen": frozen,
        "ir_checksum": checksum,
        "evidence": [
            {"evidence_id": "evidence_artifact", "source_type": "artifact",
             "authority": "workspace_artifact"},
            {"evidence_id": "evidence_tool_trace", "source_type": "tool_trace",
             "authority": "environment_runtime"},
        ],
        "rubric": {
            "rubric_id": "repo_documentation_revision_001",
            "pass_threshold": 70.0,
            "deterministic": False,
            "criteria": criteria or [
                _criterion("coverage", "文档是否覆盖必要修订。", weight=30),
                _criterion("factual", "文档是否与实现相符。", weight=30,
                           evidence=["evidence_artifact", "evidence_tool_trace"]),
                _criterion("scope", "改动是否限于文档。", weight=40),
            ],
        },
    }


def test_project_ir_rubric_normalizes_weights_and_maps_evidence():
    rubric = project_ir_rubric(_ir())
    assert isinstance(rubric, Rubric)
    assert rubric.rubric_id == "repo_documentation_revision_001"
    assert rubric.version == "sha256:abc"
    assert [q.id for q in rubric.questions] == ["coverage", "factual", "scope"]
    assert abs(sum(q.weight for q in rubric.questions) - 1.0) < 1e-9
    by_id = {q.id: q for q in rubric.questions}
    assert by_id["coverage"].weight == pytest.approx(0.3)
    assert by_id["factual"].evidence_required == ("artifact", "runtime")
    assert by_id["factual"].requires_runtime_evidence is True
    assert by_id["coverage"].requires_runtime_evidence is False
    loaded = Rubric.from_dict(rubric.to_dict())
    assert loaded.questions[0].id == "coverage"


def test_project_ir_rubric_rejects_duplicate_criterion_ids():
    ir = _ir(criteria=[
        _criterion("criterion", "one"),
        _criterion("criterion", "two"),
        _criterion("criterion", "three"),
        _criterion("criterion", "four"),
    ])
    with pytest.raises(IRRubricProjectionError, match="duplicate criterion_id"):
        project_ir_rubric(ir)


def test_project_ir_rubric_rejects_unfrozen_or_missing_checksum():
    with pytest.raises(IRRubricProjectionError, match="frozen"):
        project_ir_rubric(_ir(frozen=False))
    with pytest.raises(IRRubricProjectionError, match="ir_checksum"):
        project_ir_rubric(_ir(checksum=""))


def test_nl_docs_edit_ir_fails_until_criterion_ids_are_unique():
    if not NL_DOCS_IR.is_file():
        pytest.skip("nl-docs-edit IR is not present")
    with pytest.raises(IRRubricProjectionError, match="duplicate criterion_id"):
        project_ir_rubric_file(NL_DOCS_IR)
    derived = NL_DOCS_IR.with_name("environment-ir.unique-criteria.derived.json")
    if derived.is_file():
        rubric, _ = project_ir_rubric_file(derived)
        assert len({q.id for q in rubric.questions}) == len(rubric.questions) == 4
        assert abs(sum(q.weight for q in rubric.questions) - 1.0) < 1e-9
        Rubric.from_dict(rubric.to_dict())
        return
    payload = json.loads(NL_DOCS_IR.read_text(encoding="utf-8"))
    names = ["coverage", "factual_consistency", "preservation", "scope"]
    for item, name in zip(payload["rubric"]["criteria"], names, strict=True):
        item["criterion_id"] = name
    rubric = project_ir_rubric(payload, source_path=str(NL_DOCS_IR))
    assert [q.id for q in rubric.questions] == names
    assert abs(sum(q.weight for q in rubric.questions) - 1.0) < 1e-9
    Rubric.from_dict(rubric.to_dict())


def test_project_ir_rubric_file_writes_json(tmp_path: Path):
    source = tmp_path / "environment-ir.json"
    source.write_text(json.dumps(_ir()), encoding="utf-8")
    target = tmp_path / "evaluator" / "rubric.json"
    rubric, written = project_ir_rubric_file(source, target)
    assert written == target
    loaded = Rubric.from_dict(json.loads(target.read_text(encoding="utf-8")))
    assert loaded.rubric_id == rubric.rubric_id
    assert loaded.provenance["mode"] == "projected_from_frozen_ir"
