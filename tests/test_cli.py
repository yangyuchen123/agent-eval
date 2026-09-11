from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from agenteval.cli import _load_cases, main


def test_load_cases_rejects_duplicate_ids(tmp_path: Path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [
        {"case_id": "dup", "task": "one"},
        {"case_id": "dup", "task": "two"},
    ]}))
    with pytest.raises(SystemExit, match="duplicate"):
        _load_cases(path)


def test_octagon_eval_help_marks_compatibility():
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit) as exc:
        main(["-h"])
    assert exc.value.code == 0
    help_text = buf.getvalue()
    assert "octagon-eval" in help_text
    assert "compat" in help_text.lower()
    assert "octagon-score" in help_text


def _write_harbor_trial(root: Path) -> Path:
    trial = root / "job" / "trial-1"
    (trial / "agent").mkdir(parents=True)
    (trial / "artifacts" / "logs" / "artifacts").mkdir(parents=True)
    (trial / "specs").mkdir()
    (trial / "trial.log").write_text("done", encoding="utf-8")
    (trial / "result.json").write_text(json.dumps({
        "id": "result-1", "task_name": "task", "trial_uri": str(trial),
        "agent_info": {"name": "codex", "version": "1", "model_info": {"name": "m"}},
        "exception_info": None,
    }), encoding="utf-8")
    (trial / "config.json").write_text("{}", encoding="utf-8")
    (trial / "specs" / "task.json").write_text(json.dumps({
        "task_id": "task@1", "instruction": "Do it"}), encoding="utf-8")
    (trial / "agent" / "trajectory.json").write_text(json.dumps({
        "steps": []}), encoding="utf-8")
    (trial / "artifacts" / "logs" / "artifacts" / "answer.txt").write_text(
        "The bridge will close Monday.\n", encoding="utf-8")
    return trial


def _write_rubric(path: Path) -> Path:
    path.write_text(json.dumps({
        "schema_version": "agenteval.rubric.v1",
        "rubric_id": "stub_rubric",
        "version": "1.0.0",
        "allowed_scores": [0.0, 0.5, 1.0],
        "questions": [
            {
                "id": "semantic_answer_correctness",
                "question": "correct?",
                "anchors": "yes/no",
                "evidence": "artifact",
                "weight": 2.0,
                "score_anchors": [
                    {"score": 0.0, "description": "no"},
                    {"score": 0.5, "description": "partial"},
                    {"score": 1.0, "description": "yes"},
                ],
            },
            {
                "id": "artifact_contract_compliance",
                "question": "contract?",
                "anchors": "yes/no",
                "evidence": "artifact",
                "weight": 1.0,
                "score_anchors": [
                    {"score": 0.0, "description": "no"},
                    {"score": 0.5, "description": "partial"},
                    {"score": 1.0, "description": "yes"},
                ],
            },
            {
                "id": "runtime_evidence_quality",
                "question": "runtime?",
                "anchors": "yes/no",
                "evidence": "runtime",
                "weight": 1.0,
                "score_anchors": [
                    {"score": 0.0, "description": "no"},
                    {"score": 0.5, "description": "partial"},
                    {"score": 1.0, "description": "yes"},
                ],
            },
        ],
    }), encoding="utf-8")
    return path


def test_harbor_score_stub_writes_new_run_and_records_backend(tmp_path: Path):
    trial = _write_harbor_trial(tmp_path)
    rubric = _write_rubric(tmp_path / "rubric.json")
    run_root = tmp_path / "run-stub"
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main([
            "harbor-score",
            "--trial-root", str(trial),
            "--rubric", str(rubric),
            "--judge-backend", "stub",
            "--run-root", str(run_root),
        ])
    assert code == 0
    out = buf.getvalue()
    assert "WARNING" in out
    assert "judge_backend=stub" in out
    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["summary"]["n_scored"] == 1
    assert summary["cases"][0]["case_id"] == trial.name
    subscores = summary["cases"][0]["skills"]["runtime_multi_question_judge"]
    assert set(json.loads((run_root / "evidence" / f"{trial.name}.json").read_text())["skill_results"]["runtime_multi_question_judge"]["subscores"]) == {
        "semantic_answer_correctness", "artifact_contract_compliance", "runtime_evidence_quality",
    }
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["environment"]["judge_backend"] == "stub"
    assert (run_root / "history.jsonl").is_file()
    assert subscores["score"] == 0.5


def test_harbor_score_rejects_empty_trial_root(tmp_path: Path):
    rubric = _write_rubric(tmp_path / "rubric.json")
    with pytest.raises(SystemExit, match="no matching Harbor trials found"):
        main([
            "harbor-score",
            "--trial-root", str(tmp_path / "empty"),
            "--rubric", str(rubric),
            "--judge-backend", "stub",
            "--run-root", str(tmp_path / "run"),
        ])


def test_project_ir_rubric_cli_writes_agenteval_rubric(tmp_path: Path):
    source = tmp_path / "environment-ir.json"
    source.write_text(json.dumps({
        "schema_version": "benchmark-forge.environment-ir.v1",
        "environment_id": "env",
        "task_id": "task",
        "frozen": True,
        "ir_checksum": "sha256:cli",
        "evidence": [{"evidence_id": "evidence_artifact", "source_type": "artifact",
                       "authority": "workspace_artifact"}],
        "rubric": {
            "rubric_id": "task",
            "pass_threshold": 70,
            "deterministic": False,
            "criteria": [{
                "criterion_id": "coverage",
                "description": "covers the required edits",
                "weight": 1,
                "evidence_refs": ["evidence_artifact"],
            }],
        },
    }), encoding="utf-8")
    target = tmp_path / "rubric.json"
    assert main(["project-ir-rubric", "--ir", str(source), "--output", str(target)]) == 0
    rubric = json.loads(target.read_text(encoding="utf-8"))
    assert rubric["schema_version"] == "agenteval.rubric.v1"
    assert rubric["questions"][0]["id"] == "coverage"


def test_eval_rejects_empty_manifest(tmp_path: Path):
    cases = tmp_path / "cases.json"
    outputs = tmp_path / "outputs.json"
    cases.write_text(json.dumps({"cases": []}))
    outputs.write_text("{}")
    with pytest.raises(SystemExit, match="zero cases"):
        main([
            "eval", "--cases", str(cases), "--outputs", str(outputs),
            "--case-package", "agenteval", "--run-root", str(tmp_path / "run"),
        ])
