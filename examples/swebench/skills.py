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

import json
import os
from pathlib import Path

from agenteval import LLMBackend, RuleSkill
from agenteval.skills.rubric import FineGrainedRubric
from agenteval.protocols import Case, SkillResult

import container


# ---------------------------------------------------------------------------
# Judge model configuration for the LLM skill
#   * default: DeepSeek (key from ~/.pi/agent/auth.json or DEEPSEEK_API_KEY)
#   * override for a local vLLM judge, e.g.
#       AGENTEVAL_JUDGE_BASE_URL=http://localhost:8000/v1 \
#       AGENTEVAL_JUDGE_MODEL=Qwen/Qwen2.5-72B-Instruct
# ---------------------------------------------------------------------------

def _deepseek_api_key() -> str | None:
    env = os.environ.get("DEEPSEEK_API_KEY")
    if env:
        return env
    auth = Path.home() / ".pi" / "agent" / "auth.json"
    try:
        return json.loads(auth.read_text(encoding="utf-8"))["deepseek"]["key"]
    except (OSError, KeyError, ValueError):
        return None


def build_judge_backend() -> LLMBackend:
    return LLMBackend(
        base_url=os.environ.get("AGENTEVAL_JUDGE_BASE_URL", "https://api.deepseek.com"),
        model=os.environ.get("AGENTEVAL_JUDGE_MODEL", "deepseek-v4-flash"),
        api_key=_deepseek_api_key(),
        wire_api="chat",
        json_mode=True,
        temperature=0.0,
        max_tokens=2048,
        # reasoning models burn tokens on reasoning_content; judge doesn't
        # need to think out loud — disable it for speed and cost
        extra_body={"thinking": {"type": "disabled"}},
    )



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
                "collected": result.get("collected", []),
                "ids_dropped": result.get("ids_dropped", []),
                "raw_output_tail": result["raw_output"][-3000:],
            },
        )


class PatchQualitySkill(FineGrainedRubric):
    """SWE-bench patch code-review rubric (data-driven, HarnessEval-style).

    The rubric itself lives in `rubrics/patch_quality.json` — a versioned,
    serializable artifact that Phase-2 history and Phase-3 analysis can
    consume. This class only declares identity; all mechanics (two-stage
    analyze/verify, discrete ladder, verbatim-evidence checks, aggregation)
    come from the `FineGrainedRubric` base class.
    """

    skill_id = "patch_quality"
    role = "diagnostic"
    question = ("Beyond passing tests, is the patch a high-quality fix "
                "(root cause, minimal, readable, low regression risk)?")
    rubric_path = Path(__file__).resolve().parent / "rubrics" / "patch_quality.json"

    def __init__(self, backend):
        from agenteval.rubrics import RubricStore
        rubric = RubricStore(self.rubric_path.parent).load(self.rubric_path.stem)
        super().__init__(backend, rubric)


def build_registry(enable_quality: bool = True) -> "agenteval.SkillRegistry":
    from agenteval import SkillRegistry
    registry = SkillRegistry()
    registry.register(PatchAppliesSkill())
    registry.register(TestResolutionSkill())
    if enable_quality:
        registry.register(PatchQualitySkill(build_judge_backend()))
    return registry


def build_router(registry: "agenteval.SkillRegistry"):
    from agenteval import Plan, RuleRouter

    def route(case: Case, catalog: list[dict]) -> Plan:
        selected = [
            {"skill_id": "patch_applies", "role": "observation",
             "reason": "patch must apply cleanly before tests can run",
             "parameters": {}},
            {"skill_id": "test_resolution", "role": "core",
             "reason": "SWE-bench resolution = F2P pass + P2P no regression",
             "parameters": {}},
        ]
        # include every diagnostic skill registered (rubric-style deep checks)
        for spec in catalog:
            if spec.get("role") == "diagnostic":
                selected.append({
                    "skill_id": spec["skill_id"], "role": "diagnostic",
                    "reason": "diagnostic deep-check (does not affect resolved)",
                    "parameters": {}})
        return Plan(case_id=case.case_id, selected_skills=tuple(selected),
                    skipped_skills=())
    return RuleRouter(route)


SKILL_WEIGHTS = {"patch_applies": 0.0, "test_resolution": 1.0, "patch_quality": 0.0}
