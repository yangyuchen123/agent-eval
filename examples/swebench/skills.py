"""SWE-bench evaluation skills (plug into AgentEval).

* ``patch_applies``   (observation, rule) — can the model patch be applied
  cleanly to the testbed repo? Cheap pre-check, done in the container.
* ``test_resolution`` (core, rule)       — the real grade: apply patch in
  the container, run FAIL_TO_PASS (must pass) and PASS_TO_PASS (must not
  regress). Cached by AgentEval's digest cache: unchanged patch → no
  docker run.

Both skills are deterministic — no judge model involved. If you want an
LLM skill (e.g. patch-quality rubric), add it here and register it.
"""
from __future__ import annotations

from agenteval import RuleSkill
from agenteval.protocols import Case, SkillResult

import container


class PatchAppliesSkill(RuleSkill):
    skill_id = "patch_applies"
    role = "observation"
    question = "Can the model patch be applied cleanly to the testbed repo?"
    definition_version = "swebench.patch_applies.v1"

    def evaluate(self, case: Case, output: str) -> SkillResult:
        inst = case.context["instance"]
        try:
            result = container.run_tests(inst, output, timeout=900)
            ok = result["applied"]
        except Exception as exc:  # noqa: BLE001 - infra errors are evidence
            return SkillResult(skill_id=self.skill_id, status="error",
                               score=None,
                               diagnostics={"error": repr(exc)})
        return SkillResult(
            skill_id=self.skill_id,
            status="ok",
            score=1.0 if ok else 0.0,
            subscores={"applies_cleanly": 1.0 if ok else 0.0},
            reasons={"applies_cleanly": "git apply --check passed"
                     if ok else "model patch conflicts with testbed"},
        )


class TestResolutionSkill(RuleSkill):
    skill_id = "test_resolution"
    role = "core"
    question = ("Does the model patch make all FAIL_TO_PASS tests pass "
                "without regressing PASS_TO_PASS tests?")
    definition_version = "swebench.test_resolution.v1"

    def evaluate(self, case: Case, output: str) -> SkillResult:
        inst = case.context["instance"]
        try:
            result = container.run_tests(inst, output)
        except Exception as exc:  # noqa: BLE001
            return SkillResult(skill_id=self.skill_id, status="error",
                               score=None,
                               diagnostics={"error": repr(exc)})

        resolved = result["status"] == "ok"
        subscores = {
            "f2p_all_pass": 1.0 if not result["f2p_failed"] else 0.0,
            "p2p_no_regression": 1.0 if not result["p2p_failed"] else 0.0,
        }
        reasons = {
            "f2p_all_pass": (
                f"{len(result['f2p']['passed'])}/{len(result['f2p']['passed']) + len(result['f2p']['failed'])} "
                f"FAIL_TO_PASS passed" if not result["f2p_failed"]
                else f"FAIL_TO_PASS still failing: {result['f2p_failed']}"),
            "p2p_no_regression": (
                f"{len(result['p2p']['passed'])}/{len(result['p2p']['passed']) + len(result['p2p']['failed'])} "
                f"PASS_TO_PASS kept passing" if not result["p2p_failed"]
                else f"PASS_TO_PASS regressed: {result['p2p_failed']}"),
        }
        return SkillResult(
            skill_id=self.skill_id,
            status="ok",
            score=1.0 if resolved else 0.0,
            subscores=subscores,
            reasons=reasons,
            evidence={
                "exit_code": result["exit_code"],
                "applied": result["applied"],
                "f2p_passed": result["f2p"]["passed"],
                "p2p_passed": result["p2p"]["passed"],
                "raw_output_tail": result["raw_output"][-3000:],
            },
        )


def build_registry() -> "agenteval.SkillRegistry":
    from agenteval import SkillRegistry
    registry = SkillRegistry()
    registry.register(PatchAppliesSkill())
    registry.register(TestResolutionSkill())
    return registry


def build_router(registry: "agenteval.SkillRegistry"):
    from agenteval import Plan, RuleRouter

    def route(case: Case, catalog: list[dict]) -> Plan:
        return Plan(
            case_id=case.case_id,
            selected_skills=(
                {"skill_id": "patch_applies", "role": "observation",
                 "reason": "patch must apply cleanly before tests can run",
                 "parameters": {}},
                {"skill_id": "test_resolution", "role": "core",
                 "reason": "SWE-bench resolution = F2P pass + P2P no regression",
                 "parameters": {}},
            ),
            skipped_skills=(),
        )
    return RuleRouter(route)


SKILL_WEIGHTS = {"patch_applies": 0.0, "test_resolution": 1.0}
