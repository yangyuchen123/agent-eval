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
