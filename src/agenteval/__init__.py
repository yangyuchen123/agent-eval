"""AgentEval: agentified evaluation framework for LLM agents.

Domain-agnostic core: cases, skills, routing, evidence trees and scoring.
Evaluation cases and skills live in *case packages* outside this framework.
"""

from .analysis import (capability_report, cohen_kappa,
                       judge_rule_agreement, judge_self_consistency,
                       kendall_tau, migration_report, question_metrics,
                       render_capability_report, render_diagnostics,
                       render_migration, rubric_diagnostics, spearman)
from .backends import LLMBackend
from .history import (EvalRecord, HistoryStore, new_run_id,
                      question_stats, rubric_question_report,
                      summary_by_skill)
from .protocols import (Case, CaseEvidence, Plan, SkillResult, SkillSpec)
from .rubrics import Rubric, RubricQuestion, RubricStore
from .planner import LLMRouter, RuleRouter, validate_plan
from .runner import RunConfig, RunReport, evaluate_one, run_eval, write_evidence
from .score import (dataset_summary, simple_mean_case_score,
                    weighted_case_score)
from .skills.base import LLMSkill, RuleSkill, Skill
from .skills.registry import SkillRegistry
from .skills.rubric import FineGrainedRubric

__version__ = "0.1.0"

__all__ = [
    "Case", "CaseEvidence", "Plan", "SkillResult", "SkillSpec",
    "LLMBackend", "Rubric", "RubricQuestion", "RubricStore",
    "EvalRecord", "HistoryStore", "new_run_id",
    "question_stats", "rubric_question_report", "summary_by_skill",
    "question_metrics", "rubric_diagnostics", "render_diagnostics",
    "judge_self_consistency", "judge_rule_agreement",
    "cohen_kappa", "spearman", "kendall_tau",
    "migration_report", "render_migration",
    "capability_report", "render_capability_report",
    "LLMRouter", "RuleRouter", "validate_plan",
    "RunConfig", "RunReport", "evaluate_one", "run_eval", "write_evidence",
    "dataset_summary", "simple_mean_case_score", "weighted_case_score",
    "LLMSkill", "RuleSkill", "Skill", "SkillRegistry",
    "FineGrainedRubric",
    "__version__",
]
