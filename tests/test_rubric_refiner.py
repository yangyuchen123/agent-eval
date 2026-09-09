from agenteval.rubric_refiner import inherit_metadata, normalize_result
from agenteval.rubric_atomicity_validator import validate_atomicity


def test_keep_single_proposition():
    original = {"criterion_id": "R1", "text": "Header includes Aurisic.", "atomicity": "compound", "hardness": "hard", "judgment_type": "objective", "capability": {"primary": "spreadsheet_structure"}}
    proposal = normalize_result({"action": "KEEP", "original_criterion_id": "R1", "replacement_criteria": []}, original)
    assert validate_atomicity(original, proposal)["accept"] is True


def test_split_preserves_metadata_without_refiner_remap():
    original = {"criterion_id": "R7", "text": "Formulas are correct and formatting is preserved.", "grounding": "task_specific", "hardness": "hard", "judgment_type": "objective", "capability": {"primary": "formula_design"}}
    proposal = normalize_result({"action": "SPLIT", "original_criterion_id": "R7", "replacement_criteria": [{"criterion_id": "R7.1", "text": "Formulas are correct."}, {"criterion_id": "R7.2", "text": "Formatting is preserved."}]}, original)
    assert validate_atomicity(original, proposal)["accept"] is True
    final = inherit_metadata(original, proposal["replacement_criteria"][0])
    assert final["capability"] == original["capability"]
    assert final["atomicity"] == "atomic"
