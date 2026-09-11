from pathlib import Path
import json

import pytest

from agentjudge.gdpval_result import normalize_official_result, parse_model_json, repair_rubric_ids, score_100
from agentjudge.workbook import inspect_xlsx, render_inspect_text
from agentjudge.workbook_pi import PROTOCOL_ID, prepare_workspace

XLSX = Path("/home/yang/agent-octagon/data/attempts/att_869a93f9b7f9/skill_workspace/Aurisic_Prepaid_Amortization_Through_Apr2025.xlsx")
RUBRIC = Path("/home/yang/agent-octagon-envs/gdpval-prepaid-amortization-official/private/official_rubric.json")


def _rubric():
    return json.loads(RUBRIC.read_text())["rubric_json"]


def test_inspect_real_attempt_reads_truncated_sheet_names():
    inspect = inspect_xlsx(XLSX)
    assert inspect["status"] == "present"
    names = inspect["sheet_names"]
    assert "Prepaid Summary" in names
    assert any(n.startswith("Prepaid Expenses (Account #1250") for n in names)
    assert any(n.startswith("Prepaid Insurance (Account #125") for n in names)
    insurance = next(n for n in names if "Insurance" in n)
    assert "1251" not in insurance
    assert len(insurance) == 31
    assert insurance in inspect["excel_name_limit_31"]
    sheets = {s["name"]: s for s in inspect["sheets"]}
    expenses = next(s for s in inspect["sheets"] if "Expenses" in s["name"])
    assert expenses["formula_count"] > 100
    assert expenses["cached_formula_value_count"] == 0
    text = render_inspect_text(inspect)
    assert "excel_name_limit_31" in text
    assert "Prepaid Insurance (Account #125" in text


def test_normalize_rejects_partial_credit():
    rubric = [{"rubric_item_id": "a", "score": 2, "criterion": "x"}]
    with pytest.raises(ValueError, match="non-binary"):
        normalize_official_result(
            {"rubric_scores": [{"rubric_item_id": "a", "awarded": 1, "reason": "half"}]},
            rubric,
        )


def test_normalize_binary_passed_and_score_100():
    rubric = [
        {"rubric_item_id": "a", "score": 2, "criterion": "x"},
        {"rubric_item_id": "b", "score": 3, "criterion": "y"},
    ]
    raw = parse_model_json(
        json.dumps(
            {
                "overall": {"confidence": "high", "summary": "ok"},
                "rubric_scores": [
                    {"rubric_item_id": "a", "passed": True, "reason": "Sheet!A1", "evidence_refs": ["Sheet!A1"]},
                    {"rubric_item_id": "b", "passed": False, "reason": "missing"},
                ],
            }
        )
    )
    review = normalize_official_result(raw, rubric)
    assert review["overall"]["awarded_points"] == 2
    assert review["overall"]["max_points"] == 5
    assert review["rubric_scores"][0]["passed"] is True
    assert review["rubric_scores"][1]["passed"] is False
    assert score_100(review) == 40


def test_repair_single_near_miss_uuid():
    rubric = [
        {"rubric_item_id": "17bd2da3-75a4-49e5-8bf2-1eaef7801279", "score": 1, "criterion": "x"},
        {"rubric_item_id": "52b999af-0182-433f-965b-49330e54de07", "score": 5, "criterion": "y"},
    ]
    parsed = {
        "rubric_scores": [
            {"rubric_item_id": "17bd2da3-75a2-49e5-8bf2-1eaef7801279", "passed": True},
            {"rubric_item_id": "52b999af-0182-433f-965b-49330e54de07", "passed": False},
        ]
    }
    repaired = repair_rubric_ids(parsed, rubric)
    assert repaired["id_repairs"][0]["to"] == "17bd2da3-75a4-49e5-8bf2-1eaef7801279"
    review = normalize_official_result(repaired, rubric)
    assert review["rubric_scores"][0]["passed"] is True


def test_repair_positional_prefix_on_full_56_item_set():
    miss = "8f659265-3445-47cc-ac3d-45ef2abc9ed2"
    extra = "8f659265-3445-47e5-8bf2-1eaef7801279"
    rubric = [{"rubric_item_id": f"00000000-0000-0000-0000-{i:012d}", "score": 1, "criterion": str(i)} for i in range(55)]
    rubric.append({"rubric_item_id": miss, "score": 2, "criterion": "x"})
    scores = [{"rubric_item_id": item["rubric_item_id"], "passed": True} for item in rubric]
    scores[-1] = {"rubric_item_id": extra, "passed": False, "reason": "spliced"}
    repaired = repair_rubric_ids({"rubric_scores": scores}, rubric)
    assert repaired["id_repairs"][0]["method"] == "positional_prefix"
    assert repaired["rubric_scores"][-1]["rubric_item_id"] == miss
    review = normalize_official_result(repaired, rubric)
    assert review["rubric_scores"][-1]["passed"] is False


def test_prepare_workspace_does_not_copy_expert_by_default(tmp_path: Path):
    prepared = prepare_workspace(
        workspace=tmp_path,
        candidate=XLSX,
        rubric_path=RUBRIC,
        source_files=[Path("/home/yang/agent-octagon-envs/gdpval-prepaid-amortization-official/inputs/COA.xlsx")],
        include_expert=False,
        evaluate=False,
    )
    assert prepared["include_expert"] is False
    assert not (tmp_path / "reference").exists()
    assert (tmp_path / "candidate" / XLSX.name).is_file()
    assert (tmp_path / "inspect.json").is_file()
    assert (tmp_path / "evaluated.json").is_file()
    evaluated = json.loads((tmp_path / "evaluated.json").read_text())
    assert evaluated["status"] == "skipped"
    assert prepared["inspect"]["status"] == "present"
    assert PROTOCOL_ID == "workbook_pi_judge.v1"
