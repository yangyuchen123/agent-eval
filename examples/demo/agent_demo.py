"""Demo case package — shows how to plug a domain into AgentEval.

This package is NOT part of the framework: it lives in examples/ to
demonstrate the decoupled integration contract. Delete it and write your
own case package for your agent domain.

Contract (what the CLI needs):
    build_registry() -> SkillRegistry
    build_router(registry) -> Router
    SKILL_WEIGHTS / AGGREGATE (optional)

Domain: minimal arithmetic tasks.
    task: "3 + 4 = ?"
    expected.answer: "7"
Skills:
    task_success   (core)  — exact answer match (rule skill)
    format_check   (obs.)  — output starts with "ANSWER:" (rule skill)
    quality_judge  (diag.) — LLM judge 1-5 (optional; requires a backend)
"""
from __future__ import annotations

import re

from agenteval import (LLMBackend, LLMSkill, Plan, RuleRouter, RuleSkill,
                       SkillRegistry)
from agenteval.protocols import Case, SkillResult

# ------------------------------------------------------------ skills ----

class TaskSuccess(RuleSkill):
    skill_id = "task_success"
    role = "core"
    question = "Does the output contain the exact expected answer?"
    definition_version = "demo.task_success.v1"

    def evaluate(self, case: Case, output: str) -> SkillResult:
        expected = str(case.expected.get("answer", ""))
        text = output.strip()
        if text.startswith("ANSWER:"):
            text = text[len("ANSWER:"):].strip()
        exact = text == expected
        return SkillResult(
            skill_id=self.skill_id,
            status="ok" if expected else "invalid",
            score=1.0 if exact else 0.0,
            subscores={"exact_match": 1.0 if exact else 0.0},
            reasons={"exact_match": "output equals expected answer"
                     if exact else f"output {text!r} != expected {expected!r}"},
        )


class FormatCheck(RuleSkill):
    skill_id = "format_check"
    role = "observation"
    question = "Does the output follow the required answer format?"
    definition_version = "demo.format_check.v1"

    def evaluate(self, case: Case, output: str) -> SkillResult:
        ok = bool(re.match(r"^ANSWER:\s*\S+", output.strip()))
        return SkillResult(
            skill_id=self.skill_id,
            status="ok",
            score=1.0 if ok else 0.0,
            subscores={"has_answer_prefix": 1.0 if ok else 0.0},
            reasons={"has_answer_prefix": "starts with ANSWER:"
                     if ok else "missing ANSWER: prefix"},
        )


class QualityJudge(LLMSkill):
    """Optional diagnostic skill: a judge model scores quality 1-5.

    Enabled only when a backend is provided (see build_registry below).
    """
    skill_id = "quality_judge"
    role = "diagnostic"
    question = "Is the response clear and correct beyond exact matching?"
    definition_version = "demo.quality_judge.v1"
    judge_system = (
        "You are a strict judge. Score the response 1-5 for correctness "
        "and clarity. Return JSON: {\"score\": 1-5, \"reason\": \"...\"}"
    )

    def messages(self, case: Case, output: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.judge_system},
            {"role": "user",
             "content": f"Task: {case.task}\nExpected answer: "
                        f"{case.expected.get('answer')}\nResponse: {output}"},
        ]

    def parse(self, parsed: dict[str, object], case: Case) -> SkillResult:
        score = parsed.get("score")
        try:
            value = max(0.0, min(1.0, (float(score) - 1) / 4.0))
        except (TypeError, ValueError):
            value = None
        return SkillResult(
            skill_id=self.skill_id,
            status="ok" if value is not None else "invalid",
            score=value,
            subscores={"quality": value},
            reasons={"quality": str(parsed.get("reason", ""))},
        )


# ------------------------------------------------------------ wiring ----

def build_registry(enable_judge: bool = False) -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(TaskSuccess())
    registry.register(FormatCheck())
    if enable_judge:
        registry.register(QualityJudge(LLMBackend(
            base_url="http://localhost:8000/v1", model="Qwen/Qwen2.5-72B-Instruct",
            api_key="EMPTY", wire_api="chat", json_mode=True)))
    return registry


def build_router(registry: SkillRegistry):
    def route(case: Case, catalog: list[dict]) -> Plan:
        return Plan(
            case_id=case.case_id,
            selected_skills=(
                {"skill_id": "task_success", "role": "core",
                 "reason": "arithmetic answer must match exactly",
                 "parameters": {}},
                {"skill_id": "format_check", "role": "observation",
                 "reason": "output must follow the ANSWER: format",
                 "parameters": {}},
            ),
            skipped_skills=(),
        )
    return RuleRouter(route)


SKILL_WEIGHTS = {"task_success": 0.7, "format_check": 0.3, "quality_judge": 0.0}
