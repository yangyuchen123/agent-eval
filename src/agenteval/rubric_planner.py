"""LLM-assisted preference abstraction and case-specific rubric generation."""
from __future__ import annotations

import json
from typing import Any

from .backends import LLMBackend
from .preferences import MetaPrinciple, MetaRubric, PreferenceExample
from .protocols import Case
from .rubrics import Rubric, RubricQuestion


class RubricPlannerError(ValueError):
    pass


class RubricPlanner:
    """Turn human preference examples into auditable rubric artifacts.

    The model proposes structured data; all returned objects are validated and
    retain source-example provenance. This planner does not score agent output.
    """

    def __init__(self, backend: LLMBackend):
        self.backend = backend

    def _infer_messages(self, examples: list[PreferenceExample]) -> list[dict[str, str]]:
        payload = [x.to_dict() for x in examples]
        user = """Infer reusable human-preference principles from the preference examples below.
Do not merely summarize domains. Separate cross-case principles from case-specific details.
Every principle must cite one or more source example IDs. Return JSON only:
{"rubric_id":"...","version":"...","description":"...","principles":[{"id":"snake_case","name":"...","description":"...","positive_anchors":["..."],"negative_anchors":["..."],"source_examples":["..."],"capabilities":["..."]}],"source_examples":["..."],"provenance":{"method":"..."}}

Preference examples:
""" + json.dumps(payload, ensure_ascii=False, indent=2)
        return [
            {"role": "system", "content": "You are a rubric analyst. Return JSON only. Preserve human preference evidence and do not invent reasons."},
            {"role": "user", "content": user},
        ]

    def infer_meta_rubric(self, examples: list[PreferenceExample], *, rubric_id: str = "human_preference") -> MetaRubric:
        if not examples:
            raise RubricPlannerError("at least one preference example is required")
        response = self.backend.infer(self._infer_messages(examples))
        data = response.get("parsed") or {}
        if not isinstance(data, dict):
            raise RubricPlannerError("meta-rubric planner returned non-object JSON")
        data.setdefault("rubric_id", rubric_id)
        data.setdefault("version", "generated.1")
        try:
            result = MetaRubric.from_dict(data)
        except (KeyError, TypeError, ValueError) as exc:
            raise RubricPlannerError(f"invalid generated meta-rubric: {exc}") from exc
        source_ids = {x.example_id for x in examples}
        unknown = set(result.source_examples) - source_ids
        if unknown:
            raise RubricPlannerError(f"meta-rubric cites unknown examples: {sorted(unknown)}")
        for principle in result.principles:
            if set(principle.source_examples) - source_ids:
                raise RubricPlannerError(f"principle {principle.principle_id} cites unknown examples")
        return result

    def _instantiate_messages(self, meta: MetaRubric, case: Case) -> list[dict[str, str]]:
        user = """Instantiate a concrete rubric for this case from the supplied meta-rubric.
Keep the human preference principles, but adapt questions, anchors, weights, and evidence sources to this case.
Do not invent facts not present in the case. Every question must cite source_principles and explain its case adaptation.
Return JSON only:
{"rubric_id":"...","version":"...","description":"...","questions":[{"id":"snake_case","question":"...","anchors":"...","evidence":"...","weight":1.0,"capabilities":["..."],"lineage":["..."],"source_principles":["..."],"case_adaptation":"..."}],"meta_questions":[],"allowed_scores":[0,0.25,0.5,0.75,1],"provenance":{"source_meta_rubric":"...","source_examples":["..."]}}

Meta-rubric:
""" + json.dumps(meta.to_dict(), ensure_ascii=False, indent=2) + "\n\nCase:\n" + json.dumps(self._case_prompt_payload(case), ensure_ascii=False, indent=2)
        return [
            {"role": "system", "content": "You are a case-rubric planner. Return JSON only. Rubric questions must be observable from the supplied case evidence."},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _case_prompt_payload(case: Case) -> dict[str, Any]:
        """Keep planner input bounded and exclude evaluator-only runtime payloads.

        Octagon ``Case.context`` may contain the lossless ``_eval_sample`` with
        full traces, events, and workspace references. That payload is needed by
        scorers, but it must not be recursively serialized into the planner
        request. The planner only needs task/gold metadata and compact case
        requirements; the judge later receives the full execution evidence.
        """
        context = {
            str(key): value for key, value in case.context.items()
            if key not in {"_eval_sample", "trace", "events", "thinking", "attempt_dir", "workspace_root"}
            and not str(key).startswith("_")
        }
        return {
            "case_id": case.case_id,
            "task": case.task,
            "expected": case.expected,
            "metadata": case.metadata,
            "context": context,
        }

    def instantiate(self, meta: MetaRubric, case: Case, *, rubric_id: str | None = None) -> Rubric:
        response = self.backend.infer(self._instantiate_messages(meta, case))
        data = response.get("parsed") or {}
        if not isinstance(data, dict):
            raise RubricPlannerError("case-rubric planner returned non-object JSON")
        data.setdefault("rubric_id", rubric_id or f"{case.case_id}.rubric")
        data.setdefault("version", f"generated-from-{meta.version}")
        data.setdefault("provenance", {})
        data["provenance"] = {
            **dict(data["provenance"]),
            "source_meta_rubric": meta.rubric_id,
            "source_meta_version": meta.version,
            "source_examples": list(meta.source_examples),
            "case_id": case.case_id,
            "planner_model": self.backend.model,
        }
        try:
            questions = []
            for raw in data.get("questions") or []:
                source = tuple(str(x) for x in (raw.get("source_principles") or []))
                if not source:
                    raise RubricPlannerError(f"question {raw.get('id')!r} has no source_principles")
                questions.append(RubricQuestion.from_dict(raw))
            if not questions:
                raise RubricPlannerError("generated case rubric has no questions")
            result = Rubric(
                rubric_id=str(data["rubric_id"]), version=str(data["version"]),
                description=str(data.get("description") or ""),
                questions=tuple(questions),
                meta_questions=frozenset(str(x) for x in (data.get("meta_questions") or [])),
                allowed_scores=tuple(float(x) for x in (data.get("allowed_scores") or (0, .25, .5, .75, 1))),
                provenance=data["provenance"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RubricPlannerError(f"invalid generated case rubric: {exc}") from exc
        principle_ids = {p.principle_id for p in meta.principles}
        for question in result.questions:
            # source_principles is retained in provenance by the planner prompt;
            # lineage/capability stay compatible with the existing Rubric schema.
            if question.lineage and not set(question.lineage) & principle_ids:
                raise RubricPlannerError(f"question {question.id} lineage has no meta-principle overlap")
        return result
