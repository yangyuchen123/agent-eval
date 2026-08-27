"""AgentEval meta-evaluation and Judge reliability infrastructure."""
from .gold import GoldJudgment, load_gold, load_gold_dir, write_gold
from .metrics import compare_judgment_sets, evidence_jaccard, retrieval_metrics, score_metrics, score_summary, stability_metrics
from .perturbations import EvidenceSnapshot, add_distractors, lengthen, remove, reorder, paraphrase_question
from .runner import JudgmentObservation, MetaCase, MetaEvalRunner
from .baselines import agentic_evidence_judge, full_trace_judge, static_retrieval_judge
from .taxonomy import FailureCode, classify_failure
from .failure_validation import (FailureAttemptScan, FailureSignal, FailureSignalKind,
                                 FailureValidationStratum, candidate_strata,
                                 scan_failure_signals, select_balanced_scans)
from .report import render_report, write_report
from .octagon import OctagonAttempt, OctagonDiscovery, write_inventory
from .process_rubric import (GENERIC_RUNTIME_PROCESS_QUESTIONS,
                             GENERIC_RUNTIME_PROCESS_QUESTIONS_V2,
                             GENERIC_RUNTIME_PROCESS_QUESTIONS_V3,
                             GENERIC_RUNTIME_PROCESS_RUBRIC,
                             GENERIC_RUNTIME_PROCESS_RUBRIC_V2,
                             GENERIC_RUNTIME_PROCESS_RUBRIC_V3,
                             GENERIC_RUNTIME_PROCESS_QUESTIONS_V4,
                             GENERIC_RUNTIME_PROCESS_RUBRIC_V4,
                             GENERIC_RUNTIME_PROCESS_QUESTIONS_TWO_LEVEL,
                             GENERIC_RUNTIME_PROCESS_RUBRIC_TWO_LEVEL,
                             GENERIC_RUNTIME_PROCESS_QUESTIONS_FIVE_LEVEL,
                             GENERIC_RUNTIME_PROCESS_RUBRIC_FIVE_LEVEL,
                             build_resolution_rubric, process_questions_by_id)

__all__ = [
    "GoldJudgment", "load_gold", "load_gold_dir", "write_gold", "FailureCode", "classify_failure",
    "EvidenceSnapshot", "add_distractors", "lengthen", "remove", "reorder", "paraphrase_question",
    "MetaCase", "JudgmentObservation", "MetaEvalRunner", "agentic_evidence_judge", "full_trace_judge", "static_retrieval_judge", "evidence_jaccard", "retrieval_metrics",
    "score_metrics", "score_summary", "stability_metrics", "render_report", "write_report", "OctagonAttempt", "OctagonDiscovery", "write_inventory",
    "GENERIC_RUNTIME_PROCESS_QUESTIONS", "GENERIC_RUNTIME_PROCESS_QUESTIONS_V2",
    "GENERIC_RUNTIME_PROCESS_QUESTIONS_V3", "GENERIC_RUNTIME_PROCESS_RUBRIC",
    "GENERIC_RUNTIME_PROCESS_RUBRIC_V2", "GENERIC_RUNTIME_PROCESS_RUBRIC_V3",
    "GENERIC_RUNTIME_PROCESS_QUESTIONS_V4", "GENERIC_RUNTIME_PROCESS_RUBRIC_V4",
    "GENERIC_RUNTIME_PROCESS_QUESTIONS_TWO_LEVEL", "GENERIC_RUNTIME_PROCESS_RUBRIC_TWO_LEVEL",
    "GENERIC_RUNTIME_PROCESS_QUESTIONS_FIVE_LEVEL", "GENERIC_RUNTIME_PROCESS_RUBRIC_FIVE_LEVEL",
    "build_resolution_rubric", "process_questions_by_id",
    "FailureAttemptScan", "FailureSignal", "FailureSignalKind", "FailureValidationStratum",
    "candidate_strata", "scan_failure_signals", "select_balanced_scans",
]
