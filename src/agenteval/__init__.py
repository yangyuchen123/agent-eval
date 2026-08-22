"""AgentEval: agentified evaluation framework for LLM agents.

Domain-agnostic core: cases, skills, routing, evidence trees and scoring.
Evaluation cases and skills live in *case packages* outside this framework.
"""

from .backends import LLMBackend
from .protocols import (Case, CaseEvidence, Plan, SkillResult, SkillSpec)
from .planner import LLMRouter, RuleRouter, validate_plan
from .runner import RunConfig, RunReport, evaluate_one, run_eval, write_evidence
from .score import (dataset_summary, simple_mean_case_score,
                    weighted_case_score)
from .skills.base import LLMSkill, RuleSkill, Skill
from .skills.registry import SkillRegistry

__version__ = "0.1.0"

__all__ = [
    "Case", "CaseEvidence", "Plan", "SkillResult", "SkillSpec",
    "LLMBackend",
    "LLMRouter", "RuleRouter", "validate_plan",
    "RunConfig", "RunReport", "evaluate_one", "run_eval", "write_evidence",
    "dataset_summary", "simple_mean_case_score", "weighted_case_score",
    "LLMSkill", "RuleSkill", "Skill", "SkillRegistry",
    "__version__",
]
