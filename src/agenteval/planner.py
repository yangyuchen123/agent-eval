"""Skill routing: decide which skills evaluate a case, and why.

Two routing modes, pluggable per case package:

* ``RuleRouter``  — a deterministic callable supplied by the case package.
  Use it when skill selection is fully known in advance (e.g. golden-answer
  domains where every case uses the same skills). Free and reproducible.
* ``LLMRouter``  — an agent reads the case and the skill catalog and returns
  selected/skipped skills **with case-grounded reasons**, mirroring
  HarnessEval-W's planner. Use it when applicability genuinely depends on
  the case (open-ended domains).

Every plan is validated before use: unknown skills, duplicate selections and
invalid roles are rejected; a plan must contain at least one core skill and
(if the catalog has any) one observation skill.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .backends import LLMBackend, build_messages
from .io import value_digest
from .protocols import Case, Plan
from .rubrics import criterion_evidence_requirements, rubric_questions
from .skills.registry import SkillRegistry

VALID_ROLES = {"observation", "core", "diagnostic"}

PLANNER_PROMPT_VERSION = "agenteval.planner.v1"


class RuleFunc(Protocol):
    def __call__(self, case: Case, catalog: list[dict[str, Any]]) -> Plan: ...


# ------------------------------------------------------------- router ----

class Router(Protocol):
    def route(self, case: Case, catalog: list[dict[str, Any]]) -> Plan: ...


@dataclass
class RuleRouter:
    """Wrap a case-package callable as a router."""

    func: RuleFunc

    def route(self, case: Case, catalog: list[dict[str, Any]]) -> Plan:
        plan = self.func(case, catalog)
        return validate_plan(plan, catalog)


@dataclass
class RubricRouter:
    """Decorate an existing router with criterion-level evidence routing.

    The wrapped router remains the source of the normal case-level plan. When
    rubric questions declare ``preferred_skills`` or evidence sources, this
    decorator annotates selections with the criteria they serve and removes
    explicitly runtime-only skills that serve no runtime criterion. Rubrics
    without declarations are passed through unchanged for compatibility.
    """

    base: Router
    rubric: Any

    def route(self, case: Case, catalog: list[dict[str, Any]]) -> Plan:
        plan = self.base.route(case, catalog)
        questions = rubric_questions(self.rubric)
        if not questions:
            return plan
        specs = {str(item.get("skill_id")): item for item in catalog}
        declared = any(
            bool(criterion_evidence_requirements(q)["required"]
                  or criterion_evidence_requirements(q)["optional"]
                  or criterion_evidence_requirements(q)["preferred_skills"]
                  or criterion_evidence_requirements(q)["requires_runtime_evidence"]
                  or "evidence_required" in q or "evidence_sources" in q)
            for q in questions
        )
        if not declared:
            return plan
        assignments: dict[str, list[str]] = {str(q.get("id")): [] for q in questions}
        runtime_names = {"runtime", "runtrace", "trace", "runtime_evidence", "mcp", "tool"}
        for q in questions:
            qid = str(q.get("id") or "overall")
            req = criterion_evidence_requirements(q)
            required = {str(x).lower() for x in req["required"]}
            for item in plan.selected_skills:
                sid = str(item.get("skill_id") or "")
                spec = specs.get(sid, {})
                sources = {str(x).lower() for x in (spec.get("evidence_sources") or ())}
                matches = bool(set(req["preferred_skills"]) & {sid})
                matches = matches or bool(required & sources)
                if req["requires_runtime_evidence"] and sources & runtime_names:
                    matches = True
                if matches:
                    assignments[qid].append(sid)
        selected = []
        for item in plan.selected_skills:
            sid = str(item.get("skill_id") or "")
            criterion_ids = [qid for qid, ids in assignments.items() if sid in ids]
            spec_sources = {str(x).lower() for x in (specs.get(sid, {}).get("evidence_sources") or ())}
            is_runtime = bool(spec_sources & runtime_names or any(x in sid.lower() for x in ("trace", "runtime")))
            if declared and is_runtime and not criterion_ids:
                continue
            params = dict(item.get("parameters") or {})
            if criterion_ids:
                params["criterion_ids"] = criterion_ids
            selected.append({**item, "parameters": params})
        if not selected:
            selected = list(plan.selected_skills)
        planner = dict(plan.planner)
        planner["criterion_routing"] = {
            qid: {"selected_skills": ids, "requirements": criterion_evidence_requirements(q)}
            for qid, ids in assignments.items()
        }
        return validate_plan(Plan(
            case_id=plan.case_id, selected_skills=tuple(selected),
            skipped_skills=plan.skipped_skills, routing_mode="rubric", planner=planner), catalog)


@dataclass
class LLMRouter:
    """LLM-based router: case + catalog → plan with reasons."""

    backend: LLMBackend
    prompt_version: str = PLANNER_PROMPT_VERSION

    def _system(self) -> str:
        return (
            "You are an evaluation skill planner.\n"
            "Given a case definition and the skill catalog, select the skills "
            "that legitimately apply to evaluating an agent's output for this "
            "case, and record a concrete case-grounded reason for every skill "
            "you skip.\n"
            "Roles: observation = generic quality checks; core = the primary "
            "capability this case tests; diagnostic = optional deep checks.\n"
            "Return one JSON object only: "
            '{"selected_skills":[{"skill_id","role","reason","parameters":{}}],'
            '"skipped_skills":[{"skill_id","reason"}]}'
        )

    def route(self, case: Case, catalog: list[dict[str, Any]]) -> Plan:
        user = json.dumps(
            {"case": case.to_dict(), "skill_catalog": catalog,
             "output_schema": {
                 "selected_skills": [{"skill_id": "...", "role": "...",
                                      "reason": "...", "parameters": {}}],
                 "skipped_skills": [{"skill_id": "...", "reason": "..."}],
             }},
            ensure_ascii=False, indent=2)
        response = self.backend.infer(build_messages(self._system(), user))
        raw = response["parsed"]
        plan = Plan(
            case_id=case.case_id,
            selected_skills=tuple(raw.get("selected_skills") or []),
            skipped_skills=tuple(raw.get("skipped_skills") or []),
            routing_mode="llm",
            planner={
                "type": "openai_compatible",
                "prompt_version": self.prompt_version,
                "model": self.backend.model,
                "provenance": response["response_metadata"],
                "input_digest": value_digest({"case": case.to_dict(),
                                              "catalog": catalog}),
            },
        )
        return validate_plan(plan, catalog)


# ---------------------------------------------------------- validate -----

def validate_plan(plan: Plan, catalog: list[dict[str, Any]]) -> Plan:
    """Reject malformed plans; returns the plan unchanged when valid."""
    specs = {item["skill_id"]: item for item in catalog}
    seen: set[str] = set()
    errors: list[str] = []
    selected: list[dict[str, Any]] = []

    for raw in plan.selected_skills:
        if not isinstance(raw, dict):
            errors.append("selection is not an object")
            continue
        skill_id = str(raw.get("skill_id") or "")
        role = str(raw.get("role") or "")
        if skill_id not in specs:
            errors.append(f"unknown skill: {skill_id}")
        elif skill_id in seen:
            errors.append(f"duplicate skill: {skill_id}")
        elif role not in VALID_ROLES:
            errors.append(f"invalid role for {skill_id}: {role}")
        else:
            selected.append({
                "skill_id": skill_id,
                "role": role,
                "reason": str(raw.get("reason") or "planner selected"),
                "parameters": raw.get("parameters")
                if isinstance(raw.get("parameters"), dict) else {},
            })
            seen.add(skill_id)

    roles = {item["role"] for item in selected}
    if not roles & {"core"}:
        errors.append("plan has no core skill")
    if not roles & {"observation"} and any(
            item["role"] == "observation" for item in catalog):
        errors.append("plan has no observation skill")

    if errors:
        raise ValueError(f"invalid skill plan: {json.dumps(errors, ensure_ascii=False)}")

    skipped = []
    for raw in plan.skipped_skills:
        if not isinstance(raw, dict):
            continue
        skill_id = str(raw.get("skill_id") or "")
        if skill_id in specs and skill_id not in seen:
            skipped.append({"skill_id": skill_id,
                            "reason": str(raw.get("reason") or "not selected")})

    return Plan(
        case_id=plan.case_id,
        selected_skills=tuple(selected),
        skipped_skills=tuple(skipped),
        routing_mode=plan.routing_mode,
        planner=plan.planner,
    )
