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
    """Diagnostic LLM skill: HarnessEval-style two-stage patch review.

    Variance control (following HarnessEval-W's paper design):
    1. **analyze/verify separation** — an *analyze* agent first reads only
       the issue and extracts expected behavior + success criteria; the
       *verify* agent then scores the patch against those criteria.
       The judge cannot retro-fit the standard to the patch.
    2. **fine-grained discrete questions** — 10 narrow questions instead of
       5 broad dimensions; each score is one of {0, 0.25, 0.5, 0.75, 1}
       with per-anchor definitions (no free-form 0-1 sliders).
    3. **mandatory natural-language evidence** — every question requires a
       verbatim quote from the patch; `parse` *rejects* fabricated quotes
       (substring check against the patch), so answers must cite real code.
    4. **judgeable gate** — if the evidence is thin the question caps at 0.5.

    The gold patch is NEVER shown (anti-leakage).
    Weighted 0: resolved is decided by test_resolution.
    """

    skill_id = "patch_quality"
    role = "diagnostic"
    question = ("Beyond passing tests, is the patch a high-quality fix "
                "(root cause, minimal, readable, low regression risk)?")
    definition_version = "swebench.patch_quality.v2"

    # ------------------------------------------------------------ stage 1
    ANALYZE_SYSTEM = (
        "You are a benchmark case-specification assistant. "
        "Read ONLY the issue statement (no patch is shown to you). "
        "Extract what the fix must achieve. Return JSON only with keys: "
        '{"expected_behavior": "...", "success_criteria": [...], '
        '"affected_areas": ["file/function names"], "pitfalls": [...]}'
    )

    def analyze_messages(self, case: Case) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.ANALYZE_SYSTEM},
            {"role": "user",
             "content": f"Issue statement:\n{case.task}"},  # noqa: E501
        ]

    # ------------------------------------------------------------ stage 2
    # Q1..Q10: each with per-anchor definitions and an evidence requirement.
    RUBRIC_QUESTIONS = [
        ("Q1_root_cause",
         "Does the patch fix the root cause described by the issue, not a symptom?",
         "1.0=directly fixes the cause; 0.75=fixes cause but adds unrelated refactor; "
         "0.5=fixes part of the cause; 0.25=masks a symptom; 0=unrelated",
         "Quote the exact patch lines that address the root cause"),
        ("Q2_localization",
         "Are changes confined to the affected files/functions the issue points at?",
         "1.0=only affected areas; 0.75=1 small extra file; 0.5=spread across "
         "unrelated files; 0.25=most changes unrelated; 0=touches everything",
         "List every file touched by the patch and note any that look unrelated"),
        ("Q3_minimality",
         "Is the change the smallest that fixes the issue?",
         "1.0=every line necessary; 0.75=minor extra; 0.5=removes/rewrites "
         "logic that was needed (e.g. deletes power handling); 0.25=large "
         "rewrite; 0=bulk change with no clear purpose",
         "Quote any removed/rewritten logic that may have been necessary"),
        ("Q4_edge_cases",
         "Does the fix handle edge cases the issue implies (inverted inputs, empties, bounds)?",
         "1.0=handles them explicitly; 0.75=implicitly safe; 0.5=ignores some; "
         "0.25=breaks an edge case; 0=no edge-case thought",
         "Quote code that handles (or fails to handle) an edge case"),
        ("Q5_readability",
         "Is the new code clear and easy to follow?",
         "1.0=obvious intent, good naming; 0.75=minor friction; 0.5=confusing "
         "flow; 0.25=hard to follow; 0=incomprehensible",
         "Quote the clearest or most confusing added line"),
        ("Q6_style_consistency",
         "Is the patch consistent with the surrounding codebase style?",
         "1.0=idiomatic; 0.75=minor deviation; 0.5=notable deviation; "
         "0.25=foreign style; 0=ignores conventions",
         "Quote an added line and compare with the surrounding style"),
        ("Q7_regression_risk",
         "Is there evidence the change does not break unrelated paths?",
         "1.0=isolated, clearly safe; 0.75=local, low risk; 0.5=removes shared "
         "logic; 0.25=changes hot paths; 0=obviously risky",
         "Quote the riskiest changed line and explain why it is or is not safe"),
        ("Q8_test_alignment",
         "Does the fix match what the issue promises without modifying tests?",
         "1.0=exactly addresses the issue, tests untouched; 0.75=addresses it "
         "but touches tests; 0.5=partial; 0.25=loosely related; 0=ignores the issue",
         "Quote the patch line that most directly satisfies the issue"),
        ("Q9_clarity_of_purpose",
         "Can a reviewer tell WHAT changed and WHY without the issue text?",
         "1.0=diff is self-explanatory; 0.75=mostly; 0.5=needs the issue; "
         "0.25=opaque; 0=no discernible purpose",
         "State in one sentence what the diff does, from the diff alone"),
        ("Q10_judgeable",
         "Is the patch clear enough to judge the above questions reliably?",
         "1.0=fully judgeable; 0.75=mostly; 0.5=thin evidence; 0.25=almost "
         "nothing to judge; 0=empty patch",
         "Summarize what evidence the patch provides"),
    ]

    VERIFY_SYSTEM = (
        "You are a strict code-review judge. For each question answer with "
        "a discrete score from {0, 0.25, 0.5, 0.75, 1}, one natural-language "
        "sentence of reasoning, and a VERBATIM quote from the patch as "
        "evidence (copy the exact text — fabricated quotes are rejected). "
        "If the evidence is thin, score at most 0.5. Return JSON only:"
        '{"answers": {"Q1_root_cause": {"score": 0|0.25|0.5|0.75|1, '
        '"evidence": "exact patch text", "reason": "..."}, ...}, '
        '"summary": "2-3 sentences"}'
    )

    def verify_messages(self, case: Case, output: str,
                        analyze: dict[str, object]) -> list[dict[str, str]]:
        rubric = "\n\n".join(
            f"{qid}: {question}\n  anchors: {anchors}\n  evidence: {evid}"
            for qid, question, anchors, evid in self.RUBRIC_QUESTIONS)
        user = (
            "Expected behavior (from the issue, extracted BEFORE seeing the "
            "patch):\n" + json.dumps(analyze, ensure_ascii=False, indent=1) +
            "\n\nIssue statement:\n" + case.task +
            "\n\nModel patch:\n```diff\n" + output[:6000] + "\n```\n\n" +
            "Rubric (scores must be one of 0, 0.25, 0.5, 0.75, 1):\n" + rubric)
        return [
            {"role": "system", "content": self.VERIFY_SYSTEM},
            {"role": "user", "content": user},
        ]

    # ------------------------------------------------------------ runtime
    def evaluate(self, case: Case, output: str) -> SkillResult:
        analyze_resp = self.backend.infer(self.analyze_messages(case))
        analyze = analyze_resp["parsed"]
        verify_resp = self.backend.infer(
            self.verify_messages(case, output, analyze))
        result = self.parse(verify_resp["parsed"], case, output)
        result.diagnostics["analyze_stage"] = {
            "parsed": analyze,
            "provenance": analyze_resp["response_metadata"],
        }
        result.diagnostics["judge"] = {
            "model": self.backend.model,
            "backend_digest": self.backend.config_digest,
            "provenance": verify_resp["response_metadata"],
        }
        return result

    # ------------------------------------------------------------ parsing
    def parse(self, parsed: dict[str, object], case: Case,
              output: str) -> SkillResult:
        answers = parsed.get("answers")
        if not isinstance(answers, dict):
            return SkillResult(skill_id=self.skill_id, status="invalid",
                               score=None,
                               diagnostics={"parse_error": "missing answers"})

        qids = [q[0] for q in self.RUBRIC_QUESTIONS]
        allowed = {0.0, 0.25, 0.5, 0.75, 1.0}
        subscores: dict[str, float | None] = {}
        reasons: dict[str, str] = {}
        evidence: dict[str, str] = {}
        fabricated: list[str] = []
        norm_patch = _normalize_patch(output)

        for qid in qids:
            item = answers.get(qid)
            if not isinstance(item, dict):
                subscores[qid] = None
                continue
            try:
                s = float(item.get("score"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                subscores[qid] = None
                continue
            s = s if s in allowed else min(allowed, key=lambda a: abs(a - s))
            evid = str(item.get("evidence") or "").strip()
            # anti-fabrication: every quoted fragment must appear in the patch
            # (diff-prefix and whitespace tolerant; '...' ellipses allowed).
            # Q10_judgeable is a meta question — its 'evidence' is a summary
            # of what the patch provides, so no literal quote is required.
            if (evid and qid != "Q10_judgeable"
                    and not _evidence_in_patch(evid, norm_patch)):
                fabricated.append(qid)
                evid = ""
            subscores[qid] = s
            reasons[qid] = str(item.get("reason") or "")
            evidence[qid] = evid

        valid = [v for v in subscores.values() if v is not None]
        score = round(sum(valid) / len(valid), 4) if valid else None
        return SkillResult(
            skill_id=self.skill_id,
            status="ok" if score is not None else "invalid",
            score=score,
            subscores=subscores,
            reasons=reasons,
            evidence={
                "per_question": evidence,
                "fabricated_evidence_rejected": fabricated,
                "summary": str(parsed.get("summary", "")),
            },
        )


def _normalize_whitespace(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", s).strip()


def _normalize_patch(patch: str) -> str:
    """Normalize a diff to source text (strip +/- prefixes, collapse ws)
    so quoted evidence can be matched against it."""
    import re
    lines = []
    for line in patch.splitlines():
        stripped = line.strip()
        if stripped.startswith("diff --git"):
            m = re.search(r"diff --git a/(\S+)", stripped)
            if m:
                lines.append(m.group(1))
            continue
        if stripped.startswith(("---", "+++", "index", "@@")):
            continue
        if stripped.startswith(("+", "-")):
            stripped = stripped[1:].strip()
        if stripped:
            lines.append(stripped)
    return _normalize_whitespace(" ".join(lines))


def _evidence_in_patch(evidence: str, norm_patch: str) -> bool:
    """Every quoted fragment (split on '...') must appear in the patch."""
    import re
    for segment in re.split(r"\.\.\.", evidence):
        segment = _normalize_whitespace(segment)
        if segment and segment not in norm_patch:
            return False
    return True


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
