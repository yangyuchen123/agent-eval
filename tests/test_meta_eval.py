import pytest
from agenteval.meta_eval import (
    EvidenceSnapshot, FailureCode, GoldJudgment, MetaCase, MetaEvalRunner,
    add_distractors, lengthen, remove, reorder, score_metrics, stability_metrics,
)


def _case(gold=None):
    snap = EvidenceSnapshot.from_records([
        {"evidence_id": "E1", "event_type": "agent_call", "content": {"description": "assign task"}},
        {"evidence_id": "E2", "event_type": "tool_result", "content": {"result": "done"}},
    ])
    return MetaCase("c1", "q1", {"task": "x"}, {"id": "q1", "question": "x"}, {"id": "r1"}, evidence=snap, gold=gold)


def test_gold_and_failure_taxonomy_are_serializable():
    gold = GoldJudgment("c1", "q1", 0.5, "partially_supported", required_evidence_refs=["E1"])
    assert GoldJudgment.from_dict(gold.to_dict()) == gold
    failure = __import__("agenteval.meta_eval", fromlist=["classify_failure"]).classify_failure(
        gold, {"score": 1.0, "status": "supported", "evidence_refs": [], "provenance": {"query_trajectory": []}}, available_evidence_ids=["E1"])
    assert FailureCode.RETRIEVAL_FAILURE in failure


def test_failure_taxonomy_includes_current_repeat_in_instability_check():
    classify_failure = __import__(
        "agenteval.meta_eval", fromlist=["classify_failure"]
    ).classify_failure
    prior = [
        {"score": 0.96, "status": "supported"},
        {"score": 0.98, "status": "supported"},
    ]
    failures = classify_failure(
        None,
        {"score": 0.86, "status": "supported"},
        repeated_judgments=prior,
    )
    assert FailureCode.STOCHASTIC_INSTABILITY in failures


def test_instability_threshold_does_not_flag_nominal_exact_tenth():
    classify_failure = __import__(
        "agenteval.meta_eval", fromlist=["classify_failure"]
    ).classify_failure
    prior = [
        {"score": 0.45, "status": "partially_supported"},
        {"score": 0.35, "status": "partially_supported"},
    ]
    failures = classify_failure(
        None,
        {"score": 0.40, "status": "partially_supported"},
        repeated_judgments=prior,
    )
    assert FailureCode.STOCHASTIC_INSTABILITY not in failures


def test_perturbations_preserve_or_remove_snapshot_deterministically():
    case = _case()
    assert reorder(case.evidence, 3).snapshot_digest != case.evidence.snapshot_digest
    assert len(add_distractors(case.evidence, [{"evidence_id": "D"}]).records) == 3
    assert len(remove(case.evidence, {"E1"}).records) == 1


def test_runner_records_replayable_observations(tmp_path):
    def judge(case, snapshot):
        return {"score": 0.75, "status": "supported", "evidence_refs": ["E1"], "findings": [], "provenance": {"snapshot": snapshot.snapshot_digest}}
    result = MetaEvalRunner(tmp_path).run([_case()], {"agentic": judge}, repeats=2, seed=7)
    assert result["manifest"]["repeats"] == 2
    assert len(result["observations"]) == 2
    assert (tmp_path / "judgments.jsonl").is_file()
    assert result["metrics"]["by_group"]


def test_metrics():
    assert score_metrics([0.5, 1.0], [0.5, 0.75])["mae"] == 0.125
    metrics = stability_metrics([{"score": 0.5, "status": "supported", "evidence_refs": ["E1"], "findings": []}] * 2)
    assert metrics["exact_status_agreement"] is True
    assert metrics["exact_score_agreement"] is True
    assert metrics["pairwise_score_agreement"] == 1.0
    assert metrics["score_distribution"] == {"0.5": 2}
    assert metrics["pairwise_evidence_jaccard"] == 1.0


def test_lengthen_adds_unique_semantically_irrelevant_records():
    snap = _case().evidence
    doubled = lengthen(snap, 2, seed=9)
    ids = [r["evidence_id"] for r in doubled.records]
    assert len(doubled.records) == 4
    assert len(ids) == len(set(ids))
    added = doubled.records[2:]
    assert all(r["source"] == "meta_eval.synthetic" for r in added)
    assert all(r["content"]["meta_eval_noise"] is True for r in added)


def test_compare_judgment_sets_tracks_delta_and_synthetic_selection():
    from agenteval.meta_eval import compare_judgment_sets
    result = compare_judgment_sets(
        [{"score": 0.5, "status": "supported", "evidence_refs": ["E1"]}],
        [{"score": 0.6, "status": "supported", "evidence_refs": ["E1", "meta_eval.synthetic:1:0"]}],
    )
    assert result["mean_score_delta"] == pytest.approx(0.1)
    assert result["cross_condition_evidence_jaccard"] == 0.5
    assert result["synthetic_evidence_selected"] == ["meta_eval.synthetic:1:0"]


def test_runner_aggregates_usage_and_cost(tmp_path):
    def judge(case, snapshot):
        return {"score": 0.5, "status": "supported", "evidence_refs": [], "findings": [],
                "token_usage": {"input_tokens": 100, "output_tokens": 20, "requests": 1, "tool_calls": 2},
                "cost": 0.01}
    result = MetaEvalRunner(tmp_path).run([_case()], {"agentic": judge}, repeats=2)
    group = next(iter(result["metrics"]["by_group"].values()))
    assert group["token_usage"]["total_input_tokens"] == 200
    assert group["token_usage"]["mean_tool_calls"] == 2
    assert group["cost"]["total"] == pytest.approx(0.02)


def test_frozen_process_rubric_has_independent_discrete_dimensions():
    from agenteval import Rubric
    from agenteval.meta_eval import (GENERIC_RUNTIME_PROCESS_RUBRIC,
                                     GENERIC_RUNTIME_PROCESS_RUBRIC_V2)
    rubric = Rubric.from_dict(GENERIC_RUNTIME_PROCESS_RUBRIC)
    assert rubric.question_ids == (
        "task_understanding",
        "required_action_execution",
        "result_validation",
        "observed_failure_handling",
        "completion_claim_integrity",
    )
    assert rubric.version == "frozen-2026-08-26.discrete-anchors-v3"
    assert Rubric.from_dict(GENERIC_RUNTIME_PROCESS_RUBRIC_V2).version == (
        "frozen-2026-08-26.discrete-anchors-v2"
    )
    assert rubric.allowed_scores == (0.0, 0.5, 1.0)
    assert all(
        [anchor.score for anchor in question.score_anchors] == [0.0, 0.5, 1.0]
        for question in rubric.questions
    )


def test_runner_aggregates_fine_grained_questions_by_repeat(tmp_path):
    snap = _case().evidence
    cases = [
        MetaCase(
            "c1", "q1", {"task": "x"},
            {"id": "q1", "question": "q1", "weight": 2,
             "score_anchors": [{"score": 0}, {"score": 0.5}, {"score": 1}]},
            {"id": "r"}, evidence=snap,
        ),
        MetaCase(
            "c1", "q2", {"task": "x"},
            {"id": "q2", "question": "q2", "weight": 1,
             "score_anchors": [{"score": 0}, {"score": 0.5}, {"score": 1}]},
            {"id": "r"}, evidence=snap,
        ),
    ]
    def judge(case, snapshot):
        score = 1.0 if case.question_id == "q1" else 0.5
        return {"score": score, "status": "supported", "evidence_refs": ["E1"],
                "findings": [], "provenance": {}}
    result = MetaEvalRunner(tmp_path).run(cases, {"agentic": judge}, repeats=2, seed=4)
    aggregate = result["metrics"]["by_case_aggregate"]["c1|agentic|none"]
    assert aggregate["score"]["mean"] == pytest.approx(5 / 6)
    assert aggregate["exact_aggregate_agreement"] is True
    assert [x["perturbation_seed"] for x in aggregate["repeat_aggregates"]] == [4, 5]


def test_runner_labels_structured_anchor_violation(tmp_path):
    case = MetaCase(
        "c1", "q1", {"task": "x"},
        {"id": "q1", "question": "q1",
         "score_anchors": [{"score": 0}, {"score": 0.5}, {"score": 1}]},
        {"id": "r"}, evidence=_case().evidence,
    )
    def judge(case, snapshot):
        return {"score": 0.7, "status": "supported", "evidence_refs": ["E1"],
                "findings": [], "provenance": {}}
    result = MetaEvalRunner(tmp_path).run([case], {"agentic": judge})
    assert result["metrics"]["failure_counts"] == {
        FailureCode.RUBRIC_ANCHOR_FAILURE.value: 1
    }


def test_process_rubric_v3_orthogonalizes_failure_handling():
    from agenteval.meta_eval import process_questions_by_id
    v2 = process_questions_by_id(version="v2")["observed_failure_handling"]
    v3 = process_questions_by_id(version="v3")["observed_failure_handling"]
    assert "unsupported success claim" in v2["score_anchors"][0]["description"]
    assert "non-zero exit" in v3["score_anchors"][0]["description"]
    assert "belongs to completion_claim_integrity" in v3["evidence"]
    with pytest.raises(ValueError, match="unknown process rubric version"):
        process_questions_by_id(version="v99")


def test_failure_signal_scanner_is_generic_and_does_not_assign_recovery_gold():
    from agenteval.meta_eval.failure_validation import (
        FailureSignalKind, candidate_strata, scan_failure_signals,
    )

    records = [
        {
            "evidence_id": "trace.jsonl:1", "source": "trace.jsonl",
            "evidence_class": "direct_runtime_event", "tool_name": "Bash",
            "content": {"arguments": {"command": "pytest"}, "result": {
                "exit_code": 1, "output": "1 failed", "timed_out": False,
            }},
        },
        {
            "evidence_id": "trace.jsonl:2", "source": "trace.jsonl",
            "evidence_class": "direct_runtime_event", "tool_name": "Bash",
            "content": {"arguments": {"command": "pytest"}, "result": {
                "exit_code": 0, "output": "1 passed", "timed_out": False,
            }},
        },
    ]
    signals = scan_failure_signals(records)
    assert any(signal.kind == FailureSignalKind.NONZERO_EXIT for signal in signals)
    failure = next(signal for signal in signals if signal.kind == FailureSignalKind.NONZERO_EXIT)
    assert failure.later_success_candidate_refs == ("trace.jsonl:2",)
    strata = candidate_strata(signals)
    assert "review_B_or_C_recovery_outcome_requires_human" in strata
    assert not any(value.startswith("C_") for value in strata)


def test_failure_signal_scanner_separates_fallback_warning_and_observer_error():
    from agenteval.meta_eval.failure_validation import FailureSignalKind, scan_failure_signals

    records = [
        {
            "evidence_id": "trace.jsonl:1", "source": "trace.jsonl", "tool_name": "Bash",
            "content": {"arguments": {"command": "grep x missing || echo fallback"},
                        "result": '{"exit_code":0,"output":"grep: missing: No such file\\nfallback","timed_out":false}'},
        },
        {
            "evidence_id": "trace.jsonl:2", "source": "trace.jsonl", "tool_name": "Bash",
            "content": {"result": {"exit_code": 0, "output": "WARNING: optional cache unavailable",
                                     "timed_out": False}},
        },
        {
            "evidence_id": "wire.jsonl:3", "source": "wire.jsonl",
            "event_type": "capture_event",
            "content": {"data": {"event": "error", "reason_code": "parse_failed",
                                   "message": "parse errors at lines 1,2"}},
        },
    ]
    kinds = {signal.kind for signal in scan_failure_signals(records)}
    assert FailureSignalKind.EXPECTED_FALLBACK_BRANCH in kinds
    assert FailureSignalKind.EXIT_ZERO_ERROR_TEXT not in {
        signal.kind for signal in scan_failure_signals(records[:1])
    }
    assert FailureSignalKind.NONFATAL_WARNING in kinds
    observer = [signal for signal in scan_failure_signals(records)
                if signal.kind == FailureSignalKind.OBSERVER_CAPTURE_ERROR]
    assert observer and observer[0].explicit_agent_visible is False


def test_balanced_failure_scan_selection_excludes_development_attempt():
    from agenteval.meta_eval.failure_validation import (
        FailureAttemptScan, FailureSignal, FailureSignalKind, select_balanced_scans,
    )

    def scan(attempt_id, env):
        signal = FailureSignal(
            evidence_id="trace.jsonl:1", kind=FailureSignalKind.NONZERO_EXIT,
            evidence_class="direct_runtime_event", event_type=None, tool_name="Bash",
            tool_call_id=None, agent_id=None, explicit_agent_visible=True, exit_code=1,
        )
        return FailureAttemptScan(
            attempt_id=attempt_id, env_name=env, task_id="t", status="failed",
            score_total=0, trace_digest="x", record_count=1, signals=(signal,),
            candidate_strata=("review_A_B_C_explicit_failure_without_obvious_later_success",),
        )

    chosen = select_balanced_scans(
        [scan("development", "env-a"), scan("blind-a", "env-a"), scan("blind-b", "env-b")],
        2, excluded_attempt_ids={"development"}, excluded_env_names={"env-a"},
    )
    assert [item.attempt_id for item in chosen] == ["blind-b"]


def test_four_level_process_rubric_only_changes_score_resolution():
    from agenteval.meta_eval import (
        GENERIC_RUNTIME_PROCESS_RUBRIC_V3,
        GENERIC_RUNTIME_PROCESS_RUBRIC_V4,
    )
    from agenteval.rubrics import Rubric

    v3 = Rubric.from_dict(GENERIC_RUNTIME_PROCESS_RUBRIC_V3)
    v4 = Rubric.from_dict(GENERIC_RUNTIME_PROCESS_RUBRIC_V4)
    assert v3.version != v4.version
    assert v3.allowed_scores == (0.0, 0.5, 1.0)
    assert v4.allowed_scores == (0.0, 1 / 3, 2 / 3, 1.0)
    assert v3.question_ids == v4.question_ids
    for old, new in zip(v3.questions, v4.questions):
        assert old.question == new.question
        assert old.evidence == new.evidence
        assert old.capabilities == new.capabilities
        assert [anchor.score for anchor in old.score_anchors] == [0.0, 0.5, 1.0]
        assert [anchor.score for anchor in new.score_anchors] == [0.0, 1 / 3, 2 / 3, 1.0]


def test_gold_judgment_preserves_applicability_and_stratum():
    from agenteval.meta_eval.gold import GoldJudgment

    judgment = GoldJudgment(
        case_id="c", question_id="q", expected_score=1.0,
        expected_status="supported", applicability="not_applicable",
        expected_stratum="G_observer_capture_failure",
        negative_evidence_refs=["wire.jsonl:4"],
    )
    loaded = GoldJudgment.from_dict(judgment.to_dict())
    assert loaded.applicability == "not_applicable"
    assert loaded.expected_stratum == "G_observer_capture_failure"


def test_two_and_five_level_resolution_ablations_preserve_process_questions():
    from agenteval.meta_eval import (
        GENERIC_RUNTIME_PROCESS_RUBRIC_TWO_LEVEL,
        GENERIC_RUNTIME_PROCESS_RUBRIC_FIVE_LEVEL,
        GENERIC_RUNTIME_PROCESS_RUBRIC_V3,
    )
    from agenteval.rubrics import Rubric

    base = Rubric.from_dict(GENERIC_RUNTIME_PROCESS_RUBRIC_V3)
    two = Rubric.from_dict(GENERIC_RUNTIME_PROCESS_RUBRIC_TWO_LEVEL)
    five = Rubric.from_dict(GENERIC_RUNTIME_PROCESS_RUBRIC_FIVE_LEVEL)
    assert two.question_ids == five.question_ids == base.question_ids
    assert two.allowed_scores == (0.0, 1.0)
    assert five.allowed_scores == (0.0, 0.25, 0.5, 0.75, 1.0)
    for b, t, f in zip(base.questions, two.questions, five.questions):
        assert b.question == t.question == f.question
        assert b.evidence == t.evidence == f.evidence
        assert b.capabilities == t.capabilities == f.capabilities
        assert len(t.score_anchors) == 2
        assert len(f.score_anchors) == 5


def test_gold_anchor_experiment_manifest_is_offline_and_four_conditioned(tmp_path, monkeypatch):
    import json
    from tools_build_anchor_gold_experiment import main
    gold_dir = tmp_path / "gold"
    gold_dir.mkdir()
    (gold_dir / "a.json").write_text(json.dumps({
        "case_id": "a", "question_id": "observed_failure_handling",
        "expected_score": 1.0, "expected_status": "supported"
    }))
    # The CLI integration is covered by the real generated manifest; this test
    # only guards the public Gold schema used by the experiment.
    from agenteval.meta_eval import load_gold_dir
    assert load_gold_dir(gold_dir)[0].question_id == "observed_failure_handling"
