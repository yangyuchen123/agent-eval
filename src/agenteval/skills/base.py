"""Skill abstraction: the pluggable evaluation dimensions.

A *skill* answers one evaluation question for a (case, agent output) pair.
Skills come in two flavours:

* ``RuleSkill``  — deterministic code (golden-answer matching, format checks,
  trajectory replay...). Free, reproducible, task-specific.
* ``LLMSkill``  — a judge model scores the output with an explicit rubric.
  General, but costs API calls and can be noisy (validate with
  ``agenteval.analysis`` if needed).

Both produce a ``SkillResult`` whose subscores/reasons form the auditable
evidence tree.

To add a new evaluation domain you implement skills *outside* the framework
and register them in a ``SkillRegistry``; the framework never needs to know
about your domain (cases stay decoupled).
"""
from __future__ import annotations

import abc
from typing import Any

from ..backends import LLMBackend
from ..protocols import Case, SkillResult, SkillSpec

# ------------------------------------------------------------------------

class Skill(abc.ABC):
    """Base class for evaluation skills."""

    skill_id: str = ""
    role: str = "core"                 # "observation" | "core" | "diagnostic"
    question: str = ""                 # applicability question for the router
    definition_version: str = "agenteval.skill.base"

    def spec(self) -> SkillSpec:
        return SkillSpec(skill_id=self.skill_id, role=self.role,  # type: ignore[arg-type]
                         question=self.question)

    @abc.abstractmethod
    def evaluate(self, case: Case, output: str) -> SkillResult:
        """Judge one agent output for one case."""

    # -- optional hooks ----------------------------------------------------
    def prepare(self, case: Case, output: str) -> None:
        """Called before evaluate; subclass may precompute/cache resources."""


class RuleSkill(Skill):
    """Deterministic skill: implement ``evaluate`` with plain Python.

    Ground truth comes from ``case.expected``; the case context (env tables,
    replay state) from ``case.context``.
    """
    pass


class LLMSkill(Skill):
    """Judge-model skill: implement ``messages`` and ``parse``.

    The framework takes care of calling the backend, provenance capture and
    result construction.
    """

    judge_system: str = "You are a strict evaluation judge. Return JSON only."

    def __init__(self, backend: LLMBackend):
        if not isinstance(backend, LLMBackend):
            raise TypeError("LLMSkill requires an agenteval.backends.LLMBackend")
        self.backend = backend

    def messages(self, case: Case, output: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def parse(self, parsed: dict[str, Any], case: Case) -> SkillResult:
        raise NotImplementedError

    # framework-side execution -------------------------------------------
    def evaluate(self, case: Case, output: str) -> SkillResult:
        response = self.backend.infer(self.messages(case, output))
        result = self.parse(response["parsed"], case)
        result.diagnostics["judge"] = {
            "model": self.backend.model,
            "backend_digest": self.backend.config_digest,
            "provenance": response["response_metadata"],
        }
        result.diagnostics["judge_prompt"] = {
            "system": self.judge_system,
            "user": self.messages(case, output)[-1]["content"]
            if isinstance(self.messages(case, output)[-1], dict) else "",
        }
        return result
