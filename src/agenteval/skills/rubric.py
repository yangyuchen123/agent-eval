"""FineGrainedRubric: the variance-controlled LLM rubric skill base.

Encapsulates the HarnessEval-W rubric mechanics as a reusable base class
so any domain can get them by *declaring questions* (data), not by
copying pipeline code:

1. analyze/verify two-stage separation — stage 1 reads only the case
   (no agent output) and extracts expected behavior; stage 2 scores the
   output against it.
2. discrete score ladder — every question scores one of
   ``rubric.allowed_scores`` (default {0, .25, .5, .75, 1}) with
   per-anchor definitions.
3. mandatory verbatim evidence — quotes must appear in the output;
   fabricated quotes are rejected and recorded.
4. aggregation policy — mean / weighted / multiplicative-gate
   (HarnessEval's ``visibility × judgeable × core``).

Subclasses declare a ``Rubric`` (data) and optionally override
``analyze_prompt`` / ``aggregate``.
"""

from __future__ import annotations

import json
from typing import Any

from ..backends import LLMBackend
from ..protocols import Case, SkillResult
from ..rubrics import Rubric, evidence_in_patch, normalize_patch
from .base import LLMSkill


class FineGrainedRubric(LLMSkill):
    """Base class for rubric-driven LLM skills.

    Subclass contract:
        rubric: Rubric                     (required)
        skill_id / role / question         (inherited from Skill)
        analyze_prompt(case) -> str        (optional override)
    """

    rubric: Rubric = None  # type: ignore[assignment]  # set by subclass/init
    # prompt/evaluator design version — independent from the rubric data
    # version (changing the judge prompt must NOT be confused with changing
    # the rubric questions)
    EVALUATOR_VERSION = "1"
    judge_system: str = (
        "You are a strict evaluation judge. Answer each question with a "
        "discrete score, a one-sentence reason, and a verbatim quote from "
        "the output as evidence. Fabricated quotes are rejected. "
        "If evidence is thin, score at most 0.5. "
        "Return a FLAT JSON object only, never nested: the top-level keys "
        "are EXACTLY the question ids listed in the rubric, values are the "
        "discrete scores; add \"reasons\" and \"evidence\" objects keyed "
        "by the same question ids."
    )
    analyze_system: str = (
        "You are a benchmark case-specification assistant. Read ONLY the "
        "case (no agent output is shown). Extract what a good answer must "
        "achieve. Return JSON only."
    )

    def __init__(self, backend: LLMBackend, rubric: Rubric):
        super().__init__(backend)
        if not isinstance(rubric, Rubric) or not rubric.questions:
            raise ValueError("FineGrainedRubric requires a Rubric with questions")
        self.rubric = rubric
        self.definition_version = (
            f"{self.skill_id}.evaluator.v{self.EVALUATOR_VERSION}"
            f".rubric.v{self.rubric.version}")

    # ------------------------------------------------------------ stage 1
    def analyze_prompt(self, case: Case) -> str:
        return f"Case:\n{case.task}"

    def analyze_messages(self, case: Case) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.analyze_system},
            {"role": "user", "content": self.analyze_prompt(case)},
        ]

    # ------------------------------------------------------------ stage 2
    def _rubric_text(self) -> str:
        blocks = []
        for q in self.rubric.questions:
            blocks.append(
                f"{q.id}: {q.question}\n  anchors: {q.anchors}\n"
                f"  evidence: {q.evidence}")
        return "\n\n".join(blocks)

    def verify_messages(self, case: Case, output: str,
                        analyze: dict[str, Any]) -> list[dict[str, str]]:
        allowed = " | ".join(str(s) for s in self.rubric.allowed_scores)
        user = (
            "Expected behavior (extracted BEFORE seeing the output):\n"
            + json.dumps(analyze, ensure_ascii=False, indent=1)
            + "\n\nCase:\n" + case.task
            + "\n\nAgent output:\n```\n" + output[:6000] + "\n```\n\n"
            + f"Rubric (scores must be one of {allowed}):\n"
            + self._rubric_text())
        return [
            {"role": "system", "content": self.judge_system},
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
            "rubric_id": self.rubric.rubric_id,
            "rubric_version": self.rubric.version,
            "evaluator_version": self.EVALUATOR_VERSION,
            "temperature": self.backend.temperature,
            "provenance": verify_resp["response_metadata"],
        }
        return result

    # ------------------------------------------------------------ parsing
    def parse(self, parsed: dict[str, Any], case: Case,
              output: str) -> SkillResult:
        answers = parsed.get("answers")
        flat_scores = parsed if not isinstance(answers, dict) else None
        flat_reasons = parsed.get("reasons") if flat_scores else None
        flat_evidence = parsed.get("evidence") if flat_scores else None

        allowed = set(self.rubric.allowed_scores)
        norm_patch = normalize_patch(output)
        subscores: dict[str, float | None] = {}
        reasons: dict[str, str] = {}
        evidence: dict[str, str] = {}
        fabricated: list[str] = []

        for q in self.rubric.questions:
            if flat_scores is not None:
                # flat form: {"Q1": 0|1, ...} or {"Q1": {"score": ...}, ...}
                raw_score = flat_scores.get(q.id)
                if isinstance(raw_score, dict):
                    raw_score = raw_score.get("score")
                item = {"score": raw_score,
                        "evidence": (flat_evidence or {}).get(q.id) if isinstance(flat_evidence, dict) else None,
                        "reason": (flat_reasons or {}).get(q.id) if isinstance(flat_reasons, dict) else None}
            else:
                item = answers.get(q.id)
            if not isinstance(item, dict):
                subscores[q.id] = None
                continue
            try:
                s = float(item.get("score"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                subscores[q.id] = None
                continue
            s = s if s in allowed else min(allowed, key=lambda a: abs(a - s))
            evid = str(item.get("evidence") or "").strip()
            if (evid and not self.rubric.is_meta(q.id)
                    and not evidence_in_patch(evid, norm_patch)):
                fabricated.append(q.id)
                evid = ""
            subscores[q.id] = s
            reasons[q.id] = str(item.get("reason") or "")
            evidence[q.id] = evid

        score = self.aggregate(subscores)
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

    # -------------------------------------------------------- aggregation
    def aggregate(self, subscores: dict[str, float | None]) -> float | None:
        """Default: weighted mean of valid scores. Override for gated
        aggregation (e.g. HarnessEval's visibility × judgeable × core)."""
        total_w = 0.0
        acc = 0.0
        weights = {q.id: q.weight for q in self.rubric.questions}
        for qid, s in subscores.items():
            if s is None:
                continue
            w = weights.get(qid, 1.0)
            if w <= 0:
                continue
            acc += s * w
            total_w += w
        if total_w <= 0:
            return None
        return round(acc / total_w, 4)
