"""AgentEval: agentified evaluation framework for LLM agents.

Domain-agnostic core: cases, skills, routing, evidence trees and scoring.
Evaluation cases and skills live in *case packages* outside this framework.

Public exports are the evaluation contract. Transitional Octagon runtime
client, in-process LLM judge, and runtime evidence retrieval stay in
``agenteval.adapters`` and are not part of the package root API.
"""

from .analysis import (capability_report, cohen_kappa,
                       judge_rule_agreement, judge_self_consistency,
                       kendall_tau, migration_report, question_metrics,
                       render_capability_report, render_diagnostics,
                       render_migration, rubric_diagnostics, spearman)
from .backends import LLMBackend
from .adapters import (AgentIdentity, AgentOctagonAdapter, HarborAdapter,
                       ArtifactRef, ConversationTurn, EvalSample,
                       OctagonEnvironmentSkill, OctagonScorerBridge,
                       OctagonScorerError, score_octagon_samples,
                       JsonRuntimeAdapter, RuntimeAdapter, ToolCall)
from .adapters.forge_ir import IRRubricProjectionError, project_ir_rubric, project_ir_rubric_file
from .capabilities import Capability, CapabilityStore, DEFAULT_TAXONOMY
from .history import (EvalRecord, HistoryStore, new_run_id,
                      question_stats, rubric_question_report,
                      summary_by_skill)
from .judge import (HttpJudgeClient, JudgeClient, JudgeClientError, JudgeClientSkill,
                       MultiQuestionJudgeSkill, JudgeRequest, JudgeResponse,
                       StubJudgeClient, build_judge_client)
from .meta_eval import (EvidenceSnapshot, FailureCode, GoldJudgment, JudgmentObservation, MetaCase, MetaEvalRunner, add_distractors, classify_failure, lengthen, remove, reorder, score_metrics, stability_metrics)
from .manifest import (EvaluationRun, build_manifest, evaluator_snapshot,
                       load_manifest, write_manifest)
from .protocols import (Case, CaseEvidence, Plan, SkillResult, SkillSpec)
from .rubrics import Rubric, RubricQuestion, RubricStore, ScoreAnchor, criterion_evidence_requirements, rubric_questions
from .preferences import MetaPrinciple, MetaRubric, PreferenceExample, PreferenceStore
from .rubric_planner import RubricPlanner, RubricPlannerError
from .rubric_bugfind import bugfind_prompt
from .rubric_refiner import inherit_metadata, normalize_result, refiner_prompt
from .rubric_atomicity_validator import atomicity_validator_prompt, validate_atomicity
from .rrd_optimizer import CalibrationResponse, OptimizationConfig, RRDRubricOptimizer
from .planner import LLMRouter, RubricRouter, RuleRouter, validate_plan
from .runner import RunConfig, RunReport, evaluate_one, run_eval, write_evidence
from .score import (dataset_summary, simple_mean_case_score,
                    weighted_case_score)
from .skills.base import LLMSkill, RuleSkill, Skill
from .skills.registry import SkillRegistry
from .skills.rubric import FineGrainedRubric
from .runtime_judge import score_runtime_samples

__version__ = "0.1.0"

__all__ = [
    "Case", "CaseEvidence", "Plan", "SkillResult", "SkillSpec",
    "AgentIdentity", "AgentOctagonAdapter", "HarborAdapter", "ArtifactRef",
    "ConversationTurn", "EvalSample", "OctagonEnvironmentSkill",
    "OctagonScorerBridge", "OctagonScorerError", "score_octagon_samples",
    "JsonRuntimeAdapter", "RuntimeAdapter", "ToolCall",
    "IRRubricProjectionError", "project_ir_rubric", "project_ir_rubric_file",
    "LLMBackend", "HttpJudgeClient", "StubJudgeClient", "build_judge_client",
    "MultiQuestionJudgeSkill", "JudgeClient",
    "JudgeClientError", "JudgeClientSkill", "JudgeRequest", "JudgeResponse",
    "Rubric", "RubricQuestion", "RubricStore", "PreferenceExample",
    "PreferenceStore", "MetaPrinciple", "MetaRubric", "RubricPlanner",
    "RubricPlannerError", "criterion_evidence_requirements", "rubric_questions",
    "Capability", "CapabilityStore", "DEFAULT_TAXONOMY",
    "GoldJudgment", "FailureCode", "MetaCase", "JudgmentObservation",
    "MetaEvalRunner", "EvidenceSnapshot", "reorder", "add_distractors",
    "lengthen", "remove", "classify_failure", "score_metrics",
    "stability_metrics",
    "EvaluationRun", "build_manifest", "evaluator_snapshot",
    "load_manifest", "write_manifest",
    "EvalRecord", "HistoryStore", "new_run_id",
    "question_stats", "rubric_question_report", "summary_by_skill",
    "question_metrics", "rubric_diagnostics", "render_diagnostics",
    "judge_self_consistency", "judge_rule_agreement",
    "cohen_kappa", "spearman", "kendall_tau",
    "migration_report", "render_migration",
    "capability_report", "render_capability_report",
    "LLMRouter", "RubricRouter", "RuleRouter", "validate_plan",
    "bugfind_prompt", "refiner_prompt", "normalize_result", "inherit_metadata",
    "atomicity_validator_prompt", "validate_atomicity", "RRDRubricOptimizer",
    "OptimizationConfig", "CalibrationResponse",
    "RunConfig", "RunReport", "evaluate_one", "run_eval", "write_evidence",
    "dataset_summary", "simple_mean_case_score", "weighted_case_score",
    "score_runtime_samples",
    "LLMSkill", "RuleSkill", "Skill", "SkillRegistry",
    "FineGrainedRubric",
    "__version__",
]
