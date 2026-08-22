"""Rubric diagnostics tests — no LLM, no network."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from agenteval import (EvalRecord, question_metrics,  # noqa: E402
                       render_diagnostics, rubric_diagnostics)
from agenteval.analysis import judge_self_consistency  # noqa: E402


def rec(case: str, skill: str, score: float, subscores: dict,
        rubric_id: str = "r", version: str = "1") -> EvalRecord:
    return EvalRecord(run_id="run", model_id="m", case_id=case, skill_id=skill,
                      score=score, subscores=subscores, rubric_id=rubric_id,
                      rubric_version=version)


def test_question_metrics_keep():
    """Spreading scores that track the total → healthy discriminator."""
    records = [
        rec(f"c{i}", "q", 0.2 + 0.2 * i, {"Q1": 0.2 + 0.2 * i})
        for i in range(5)
    ]
    m = question_metrics(records, "Q1")
    assert m["n"] == 5
    assert m["std"] > 0.05
    assert m["discrimination"] is not None and m["discrimination"] > 0.9
    assert m["recommendation"]["action"] == "keep"


def test_question_metrics_ceiling():
    """Everyone at max → ceiling (no discrimination)."""
    records = [rec(f"c{i}", "q", 1.0, {"Q1": 1.0}) for i in range(4)]
    m = question_metrics(records, "Q1")
    assert m["std"] == 0.0
    assert m["recommendation"]["action"] == "ceiling"


def test_question_metrics_noisy():
    """Spread but uncorrelated with total → noisy."""
    # Q1 jitters around while total trends upward → corr ≈ 0
    records = [
        rec("c0", "q", 0.50, {"Q1": 0.5}),
        rec("c1", "q", 0.60, {"Q1": 0.9}),
        rec("c2", "q", 0.70, {"Q1": 0.2}),
        rec("c3", "q", 0.80, {"Q1": 0.7}),
        rec("c4", "q", 0.90, {"Q1": 0.3}),
    ]
    m = question_metrics(records, "Q1")
    assert m["std"] > 0.05
    corr = m["discrimination"]
    # small-sample noise: accept None or weak correlation
    assert corr is None or abs(corr) < 0.4
    assert m["recommendation"]["action"] in ("noisy", "review")


def test_question_metrics_insufficient():
    m = question_metrics([rec("c1", "q", 0.5, {"Q1": 0.5})], "Q1")
    assert m["recommendation"]["action"] == "insufficient_data"


def test_entropy_uniform_vs_constant():
    uni = question_metrics(
        [rec(f"c{i}", "q", 0.5, {"Q1": v}) for i, v in
         enumerate([0.0, 0.25, 0.5, 0.75, 1.0])], "Q1")
    const = question_metrics(
        [rec(f"c{i}", "q", 1.0, {"Q1": 1.0}) for i in range(4)], "Q1")
    assert uni["entropy"] > const["entropy"]


def test_diagnostics_report_and_render():
    records = ([rec(f"c{i}", "q", 0.2 + 0.2 * i, {"Q1": 0.2 + 0.2 * i,
                                                  "Q2": 1.0})
                for i in range(5)])
    rep = rubric_diagnostics(records, "r")
    assert rep["n_questions"] == 2
    assert rep["summary"]["keep"] == 1          # Q1
    assert rep["summary"]["review"] == 1        # Q2 ceiling
    text = render_diagnostics(rep)
    assert "Q1" in text and "keep" in text
    assert "Q2" in text and "ceiling" in text


def test_judge_self_consistency():
    records = [rec("c1", "q", s, {"Q1": s}) for s in (0.8, 0.8, 0.6)]
    out = judge_self_consistency(records)
    assert out["n_repeated"] == 1
    assert out["mean_std"] == pytest.approx(0.0943, abs=1e-3)
    assert "c1::q" in out["by_item"]


def test_evaluator_version_recorded():
    r = EvalRecord(run_id="r", model_id="m", case_id="c", skill_id="q",
                   score=0.5, subscores={}, evaluator_version="2",
                   judge="j", judge_temperature=0.7)
    d = r.to_dict()
    back = EvalRecord.from_dict(d)
    assert back.evaluator_version == "2"
    assert back.judge_temperature == 0.7


# ----------------------------------------------------- judge reliability ---

def test_cohen_kappa_perfect_and_random():
    from agenteval import cohen_kappa
    assert cohen_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0
    # two raters each 50% pass, perfectly anti-correlated → worse than chance
    assert cohen_kappa([1, 1, 0, 0], [0, 0, 1, 1]) < 0


def test_spearman_perfect_and_inverse():
    from agenteval import spearman
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0


def test_judge_rule_agreement_pairs_and_reports():
    from agenteval import judge_rule_agreement
    records = []
    # 4 cases: judge and rule agree on 3, disagree on 1
    for i, (js, rs) in enumerate([(0.9, 1.0), (0.8, 1.0), (0.2, 0.0), (0.4, 1.0)]):
        records.append(EvalRecord(run_id="r", model_id="m", case_id=f"c{i}",
                                  skill_id="judge", score=js, subscores={}))
        records.append(EvalRecord(run_id="r", model_id="m", case_id=f"c{i}",
                                  skill_id="rule", score=rs, subscores={}))
    out = judge_rule_agreement(records, "judge", "rule")
    assert out["n_paired"] == 4
    assert out["confusion"] == {"tp": 2, "fp": 0, "fn": 1, "tn": 1}
    # agreement on 3/4 with both having balanced rates → positive kappa
    assert out["cohen_kappa"] is not None and out["cohen_kappa"] > 0
    assert out["spearman_rho"] is not None


def test_judge_rule_agreement_insufficient():
    from agenteval import judge_rule_agreement
    out = judge_rule_agreement([], "judge", "rule")
    assert out["n_paired"] == 0
    assert "cohen_kappa" not in out


# ------------------------------------------------------ version migration ---

def test_kendall_tau_perfect_and_inverted():
    from agenteval import kendall_tau
    assert kendall_tau([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert kendall_tau([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0
    assert kendall_tau([1, 2], [5, 5]) is None          # tie → no pairs


def _mig_records(v1: list[float], v2: list[float]):
    recs = []
    for i, (a, b) in enumerate(zip(v1, v2)):
        recs.append(EvalRecord(run_id="r", model_id="m", case_id=f"c{i}",
                               skill_id="q", score=a, subscores={"Q1": a},
                               rubric_id="r", rubric_version="v1"))
        recs.append(EvalRecord(run_id="r", model_id="m", case_id=f"c{i}",
                               skill_id="q", score=b, subscores={"Q1": b,
                                                                  "Q9": b},
                               rubric_id="r", rubric_version="v2"))
    return recs


def test_migration_ranking_preserved():
    from agenteval import migration_report
    # same ordering, different absolute scale → ranking fully preserved
    recs = _mig_records([0.8, 0.6, 0.4, 0.2], [0.9, 0.7, 0.5, 0.3])
    rep = migration_report(recs, "q", "v1", "v2")
    assert rep["ranking"]["spearman_rho"] == 1.0
    assert rep["ranking"]["kendall_tau"] == 1.0
    assert rep["drift"]["shift_type"] == "systematic"
    assert rep["drift"]["mean_delta"] == pytest.approx(0.1)
    assert rep["question_changes"]["added"] == ["Q9"]


def test_migration_ranking_flipped():
    from agenteval import migration_report
    # order inverted → ranking destroyed
    recs = _mig_records([0.8, 0.6, 0.4, 0.2], [0.2, 0.4, 0.6, 0.8])
    rep = migration_report(recs, "q", "v1", "v2")
    assert rep["ranking"]["spearman_rho"] == -1.0
    assert rep["drift"]["shift_type"] == "mixed"   # some up, some down


def test_migration_disagreements():
    from agenteval import migration_report
    # one case flips while others shift uniformly
    recs = _mig_records([0.8, 0.6, 0.4, 0.2],
                        [0.9, 0.7, 0.85, 0.3])     # c2: 0.4 → 0.85
    rep = migration_report(recs, "q", "v1", "v2", disagreement_threshold=0.2)
    assert rep["n_large_disagreements"] == 1
    assert rep["large_disagreements"][0]["case_id"] == "c2"
    # c2 rose 3× more than others but in the same direction → systematic
    assert rep["drift"]["shift_type"] == "systematic"


def test_migration_insufficient():
    from agenteval import migration_report
    rep = migration_report([], "q", "v1", "v2")
    assert rep.get("note")
