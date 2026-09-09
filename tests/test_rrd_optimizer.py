from agenteval.rrd_optimizer import CalibrationResponse, OptimizationConfig, Rubric, RRDRubricOptimizer
from agenteval.rrd_optimizer.metrics import behavioral_agreement, exact_duplicate_groups, filter_candidates
from agenteval.rrd_optimizer.evaluator import apply_missing_artifact_zeros, evaluation_prompt, evaluator_view, materialize_response, metrics_from_matrix


def responses():
    return [CalibrationResponse("s1", "strong", "strong one"), CalibrationResponse("s2", "strong", "strong two"), CalibrationResponse("w1", "weak", "weak one"), CalibrationResponse("w2", "weak", "weak two")]


def test_metrics_and_broad_gate():
    cfg = OptimizationConfig()
    m = metrics_from_matrix({"R1": {"s1": 1, "s2": 1, "w1": 1, "w2": 1}, "R2": {"s1": 1, "s2": 1, "w1": 0, "w2": 0}}, responses(), cfg)
    assert m["R1"].discrimination == 0
    assert m["R1"].broad_candidate is True
    assert m["R2"].discrimination == 1
    assert m["R2"].broad_candidate is False


def test_duplicate_and_behavioral_filter():
    rs = [Rubric("R1", "The workbook has correct formulas."), Rubric("R2", "The workbook has correct formulas."), Rubric("R3", "It contains formulas.")]
    matrix = {"R1": {"s1": 1, "s2": 1, "w1": 0, "w2": 0}, "R2": {"s1": 1, "s2": 1, "w1": 0, "w2": 0}, "R3": {"s1": 1, "s2": 1, "w1": 0, "w2": 0}}
    cfg = OptimizationConfig()
    metrics = metrics_from_matrix(matrix, responses(), cfg)
    kept, dropped = filter_candidates(rs, matrix, metrics)
    assert [x.rubric_id for x in kept] == ["R1", "R3"]
    assert len(dropped) == 1
    assert exact_duplicate_groups(rs) == [["R1", "R2"]]
    assert behavioral_agreement(matrix["R1"], matrix["R3"]) == 1


def test_flip_metrics_from_repeats():
    from agenteval.rrd_optimizer.metrics import flip_metrics_from_repeats
    a = {"R1": {"s1": 1, "w1": 0}, "R2": {"s1": 1, "w1": 1}}
    b = {"R1": {"s1": 0, "w1": 0}, "R2": {"s1": 1, "w1": 1}}
    c = {"R1": {"s1": 1, "w1": 0}, "R2": {"s1": 1, "w1": 1}}
    m = flip_metrics_from_repeats([a, b, c], rubric_ids=["R1", "R2"], response_ids=["s1", "w1"])
    assert m["cell_count"] == 4
    assert m["cell_flip_count"] == 1
    assert m["rubric_support_flip_count"] == 1


def test_round_snapshots_record_each_iteration_rubrics():
    rs = [Rubric("R1", "Correct formulas and required formatting.")]
    from agenteval.rrd_optimizer.models import DecompositionProposal
    def evaluate(task, rubrics, responses):
        if len(rubrics) == 1:
            return {"R1": {"s1": 1, "s2": 1, "w1": 1, "w2": 1}}
        return {"R1.1": {"s1": 1, "s2": 1, "w1": 0, "w2": 0}, "R1.2": {"s1": 1, "s2": 0, "w1": 0, "w2": 0}}
    def decompose2(task, candidates, responses, max_children):
        return [DecompositionProposal("R1", [Rubric("R1.1", "Correct formulas."), Rubric("R1.2", "Required formatting.")], "two propositions", "split")], {}
    result = RRDRubricOptimizer(evaluate, decompose2, OptimizationConfig(max_iterations=1)).optimize("t", "task", rs, responses())
    phases = [x["phase"] for x in result.round_snapshots]
    assert "evaluate" in phases and "after_split" in phases and "final" in phases
    after = next(x for x in result.round_snapshots if x["phase"] == "after_split")
    assert [r["rubric_id"] for r in after["rubrics"]] == ["R1.1", "R1.2"]


def test_optimizer_accepts_only_child_measurement_gain():
    rs = [Rubric("R1", "Correct formulas and required formatting.")]
    calls = []
    def evaluate(task, rubrics, responses):
        calls.append([r.rubric_id for r in rubrics])
        if len(rubrics) == 1:
            return {"R1": {"s1": 1, "s2": 1, "w1": 1, "w2": 1}}
        return {
            "R1.1": {"s1": 1, "s2": 1, "w1": 0, "w2": 0},
            "R1.2": {"s1": 1, "s2": 0, "w1": 0, "w2": 0},
        }
    def decompose(task, candidates, responses, max_children):
        return [{"parent_rubric_id": "R1", "action": "SPLIT", "reason": "two propositions", "children": [{"rubric_id": "R1.1", "text": "Correct formulas."}, {"rubric_id": "R1.2", "text": "Required formatting."}]}]
    # adapter-like decomposer return is normalized by a real decomposer; use model object here
    from agenteval.rrd_optimizer.models import DecompositionProposal
    def decompose2(task, candidates, responses, max_children):
        return [DecompositionProposal("R1", [Rubric("R1.1", "Correct formulas."), Rubric("R1.2", "Required formatting.")], "two propositions", "split")], {}
    result = RRDRubricOptimizer(evaluate, decompose2, OptimizationConfig(max_iterations=1)).optimize("t", "task", rs, responses())
    assert [x.rubric_id for x in result.optimized_rubrics] == ["R1.1", "R1.2"]
    assert result.decomposition_tree["R1"]["0"]["status"] == "split"


def test_broadness_is_count_based_not_discrimination_based():
    cfg = OptimizationConfig(broad_satisfied_count_threshold=2)
    rs = responses()
    m = metrics_from_matrix({"R": {"s1": 1, "s2": 1, "w1": 1, "w2": 0}}, rs, cfg)
    assert m["R"].support_count == 3
    assert m["R"].discrimination == 0.5
    assert m["R"].broad_candidate is True


def test_weak_preference_is_misalignment_not_broadness():
    cfg = OptimizationConfig(broad_satisfied_count_threshold=2)
    m = metrics_from_matrix({"R": {"s1": 0, "s2": 0, "w1": 1, "w2": 1}}, responses(), cfg)
    assert m["R"].misalignment_candidate is True
    assert m["R"].broad_candidate is False


def test_broadness_can_count_only_strong_responses():
    cfg = OptimizationConfig(broad_satisfied_count_threshold=2, broadness_quality_groups=("strong",))
    m = metrics_from_matrix({"R": {"s1": 1, "s2": 1, "w1": 1, "w2": 1}}, responses(), cfg)
    assert m["R"].support_count == 4
    assert m["R"].broad_candidate is False
    mixed = OptimizationConfig(broad_satisfied_count_threshold=2)
    assert metrics_from_matrix({"R": {"s1": 1, "s2": 1, "w1": 1, "w2": 1}}, responses(), mixed)["R"].broad_candidate is True


def test_gdpval_prompt_omits_runtrace_and_quality_group():
    cfg = OptimizationConfig(require_artifact=True, include_runtrace=False, include_agent_prose=True, include_quality_group_in_prompt=False)
    raw = CalibrationResponse.from_mapping({
        "response_id": "gpt5_1",
        "quality_group": "strong",
        "response": '{"attempt_id": "att_x", "artifact_paths": ["/tmp/missing.xlsx"], "final_agent_response": "I created the workbook."}',
    })
    prepared = materialize_response(raw, cfg)
    view = evaluator_view(prepared, cfg)
    assert "runtrace" not in view
    assert "quality_group" not in view
    assert view["artifact_status"] == "missing"
    prompt = evaluation_prompt("task", [Rubric("R1", "Has three tabs.")], [prepared], cfg)
    blob = prompt[1]["content"]
    assert '"runtrace":' not in blob
    assert '"quality_group":' not in blob
    assert "I created the workbook." in blob


def test_rrd_lineage_marks_split_kept_and_dropped():
    from agenteval.rubric_classification import build_lineage, lineage_axis_changes
    old = [{"criterion_id": "gen_001", "criterion": "tabs"}, {"criterion_id": "gen_002", "criterion": "source"}, {"criterion_id": "gen_003", "criterion": "accounts"}]
    new = [{"criterion_id": "gen_001", "criterion": "tabs"}, {"criterion_id": "gen_002.1", "criterion": "coa"}, {"criterion_id": "gen_002.2", "criterion": "pdfs"}]
    lineage = build_lineage(condition="A", old_criteria=old, new_criteria=new, dropped=[{"rubric_id": "gen_003", "reason": "weak_preference_misalignment"}])
    assert lineage["counts"]["kept"] == 1
    assert lineage["counts"]["split"] == 1
    assert lineage["counts"]["dropped_or_absent"] == 1
    old_cls = [{"criterion_id": "gen_002", "scope": "artifact", "atomicity": "compound", "capability": {"primary": "source_data_extraction"}}]
    new_cls = [{"criterion_id": "gen_002.1", "scope": "artifact", "atomicity": "atomic", "capability": {"primary": "source_data_extraction"}}]
    changes = lineage_axis_changes(old_cls, new_cls, lineage)
    split = next(x for x in changes if x["new_id"] == "gen_002.1")
    assert split["axis_changes"]["atomicity"]["old"] == "compound"
    assert split["axis_changes"]["atomicity"]["new"] == "atomic"


def test_xlsx_summary_is_not_truncated_by_default():
    from agenteval.rrd_optimizer.artifacts import DEFAULT_MAX_CHARS, DEFAULT_MAX_COLS, DEFAULT_MAX_ROWS, DEFAULT_MAX_SHEETS, render_artifact_text
    assert DEFAULT_MAX_SHEETS is None
    assert DEFAULT_MAX_ROWS is None
    assert DEFAULT_MAX_COLS is None
    assert DEFAULT_MAX_CHARS is None
    text = render_artifact_text([{"sheet_names": ["Prepaid Summary"]}])
    assert text.startswith("[")
    assert "truncated" not in text


def test_missing_artifact_is_forced_unsatisfied():
    cfg = OptimizationConfig(require_artifact=True)
    matrix = {"R1": {"s1": 1, "w1": 1}}
    rs = [
        CalibrationResponse("s1", "strong", "", artifact_status="present"),
        CalibrationResponse("w1", "weak", "", artifact_status="empty"),
    ]
    forced = apply_missing_artifact_zeros(matrix, rs, cfg)
    assert forced["R1"]["s1"] == 1
    assert forced["R1"]["w1"] == 0


def test_behavioral_similarity_warns_but_does_not_drop():
    rs = [Rubric("R1", "Formula correctness."), Rubric("R2", "Calculation correctness.")]
    matrix = {x.rubric_id: {"s1": 1, "s2": 1, "w1": 0, "w2": 0} for x in rs}
    from agenteval.rrd_optimizer.metrics import behavioral_redundancy_warnings
    warnings = behavioral_redundancy_warnings(rs, matrix, threshold=.9)
    assert len(warnings) == 1
    kept, dropped = filter_candidates(rs, matrix, metrics_from_matrix(matrix, responses(), OptimizationConfig()))
    assert len(kept) == 2 and dropped == []
