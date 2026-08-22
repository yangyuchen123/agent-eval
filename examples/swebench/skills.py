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

from agenteval import LLMBackend, LLMSkill, RuleSkill
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
                "raw_output_tail": result["raw_output"][-3000:],
            },
        )


class PatchQualitySkill(LLMSkill):
    """Diagnostic LLM skill: rubric-based patch-quality judgement.

    Scores the patch on 5 dimensions (each 0-1): root-cause targeting,
    minimality, code quality, regression risk, and test alignment.
    The gold patch is NEVER shown to the judge — the rubric must stand on
    the issue statement alone (prevents judge leakage).

    Weighted 0 in SKILL_WEIGHTS: resolved is decided by test_resolution;
    this skill adds a *diagnostic* dimension to the report.
    """

    skill_id = "patch_quality"
    role = "diagnostic"
    question = ("Beyond passing tests, is the patch a high-quality fix "
                "(root cause, minimal, readable, low regression risk)?")
    definition_version = "swebench.patch_quality.v1"

    judge_system = (
        "You are a strict code-review judge for SWE-bench patches. "
        "Score each dimension 0.0-1.0 (0 = terrible, 1 = perfect). "
        "Return JSON only with keys: "
        '{"q_scores": {"root_cause": 0.0-1.0, "minimality": 0.0-1.0, '
        '"code_quality": 0.0-1.0, "regression_risk": 0.0-1.0, '
        '"test_alignment": 0.0-1.0}, '
        '"reasons": {<same keys, one sentence each>}, "summary": "2-3 sentences"}'
    )

    def messages(self, case: Case, output: str) -> list[dict[str, str]]:
        rubric = """Rubric (0.0-1.0):
- root_cause: the fix targets the actual cause described by the issue, not a symptom.
- minimality: the smallest change that fixes the issue; no unrelated edits, dead code, or renames.
- code_quality: idiomatic, readable, consistent with the surrounding codebase style.
- regression_risk: low chance of breaking unrelated behavior (1.0 = very low risk).
- test_alignment: the fix matches what the issue promises and does not modify tests.

Issue statement:
{problem}

Model patch:
```diff
{patch}
```

Score the patch. Be strict: a patch that works but is hacky or bloated must
not get high minimality/quality scores."""
        return [
            {"role": "system", "content": self.judge_system},
            {"role": "user", "content": rubric.format(
                problem=case.task, patch=output[:6000])},
        ]

    def parse(self, parsed: dict[str, object], case: Case) -> SkillResult:
        q = parsed.get("q_scores")
        if not isinstance(q, dict):
            return SkillResult(skill_id=self.skill_id, status="invalid",
                               score=None,
                               diagnostics={"parse_error": "missing q_scores"})
        reasons = parsed.get("reasons")
        reasons = reasons if isinstance(reasons, dict) else {}

        def norm(key: str) -> float | None:
            try:
                v = float(q.get(key))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
            return max(0.0, min(1.0, v))

        subscores = {k: norm(k) for k in
                     ("root_cause", "minimality", "code_quality",
                      "regression_risk", "test_alignment")}
        valid = [v for v in subscores.values() if v is not None]
        score = round(sum(valid) / len(valid), 4) if valid else None
        return SkillResult(
            skill_id=self.skill_id,
            status="ok" if score is not None else "invalid",
            score=score,
            subscores=subscores,
            reasons={k: str(reasons.get(k, "")) for k in subscores},
            evidence={"summary": str(parsed.get("summary", ""))},
        )


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
