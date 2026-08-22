"""GDPVal skills: per-task rubric built from the task's own rubric items.

* ``GDPValJudgeSkill`` — FineGrainedRubric subclass whose questions are the
  task's rubric items (criterion + score). Aggregation is a weighted SUM:
  GDPVal total = Σ score of satisfied items; negative scores are penalties.
  The gold deliverable is never shown; the judge scores the agent's text
  output against the human-written criteria with verbatim evidence.
* ``artifact_presence`` — rule skill: does the output claim the required
  deliverable file (name/type)? Cheap pre-check (observation role).
"""
from __future__ import annotations

import re
from pathlib import Path

from agenteval import LLMBackend, RuleSkill, Rubric, RubricQuestion
from agenteval.protocols import Case, SkillResult
from agenteval.skills.rubric import FineGrainedRubric

# ---------------------------------------------------------------------------
# Judge backend (same conventions as examples/swebench/skills.py)
# ---------------------------------------------------------------------------

def _deepseek_api_key() -> str | None:
    import json
    import os
    env = os.environ.get("DEEPSEEK_API_KEY")
    if env:
        return env
    auth = Path.home() / ".pi" / "agent" / "auth.json"
    try:
        return json.loads(auth.read_text(encoding="utf-8"))["deepseek"]["key"]
    except (OSError, KeyError, ValueError):
        return None


def build_judge_backend() -> LLMBackend:
    import os
    return LLMBackend(
        base_url=os.environ.get("AGENTEVAL_JUDGE_BASE_URL", "https://api.deepseek.com"),
        model=os.environ.get("AGENTEVAL_JUDGE_MODEL", "deepseek-v4-flash"),
        api_key=_deepseek_api_key(),
        wire_api="chat",
        json_mode=True,
        temperature=0.0,
        max_tokens=8192,
        extra_body={"thinking": {"type": "disabled"}},
    )


# ---------------------------------------------------------------------------
# Per-task rubric from the task's rubric items
# ---------------------------------------------------------------------------

def rubric_from_task(task: dict) -> Rubric:
    """Build an AgentEval Rubric from GDPVal's rubric item list.

    Each item becomes one question: score 1 if the criterion is satisfied,
    0 otherwise. Weight = the item's score (negative = penalty), so the
    weighted-SUM aggregation reproduces GDPVal's total.
    """
    items = task["rubric_items"]
    questions = []
    for i, item in enumerate(items):
        criterion = str(item.get("criterion") or "").strip()
        if not criterion:
            continue
        questions.append(RubricQuestion(
            id=f"I{i:02d}",
            question=criterion,
            anchors="1 = criterion clearly satisfied by the output; "
                    "0 = not satisfied or no evidence",
            evidence="Quote the exact output text that supports your verdict",
            weight=float(item.get("score") or 0.0),
        ))
    return Rubric(
        rubric_id=f"gdpval_{task['task_id'][:8]}",
        version="1.0.0",
        description=f"GDPVal rubric — {task['occupation']} "
                    f"({len(questions)} items)",
        questions=tuple(questions),
        meta_questions=frozenset(),
        allowed_scores=(0.0, 1.0),
    )


class GDPValJudgeSkill(FineGrainedRubric):
    """Judge the agent's output against the task's own rubric items."""

    skill_id = "gdpval_judge"
    role = "core"
    question = ("Does the output satisfy each human-written criterion "
                "of the professional deliverable rubric?")
    EVALUATOR_VERSION = "1"

    def __init__(self, backend: LLMBackend, task: dict):
        super().__init__(backend, rubric_from_task(task))

    # GDPVal total = Σ (item score if satisfied) — weighted SUM, not mean.
    def aggregate(self, subscores: dict[str, float | None]) -> float | None:
        total = 0.0
        weights = {q.id: q.weight for q in self.rubric.questions}
        for qid, s in subscores.items():
            if s is None:
                continue
            w = weights.get(qid, 1.0)
            total += s * w
        return round(total, 4)


class ArtifactPresenceSkill(RuleSkill):
    """Cheap rule pre-check: does the output claim the required deliverable?"""

    skill_id = "artifact_presence"
    role = "observation"
    question = "Does the output reference the required deliverable file?"
    definition_version = "gdpval.artifact_presence.v1"

    def evaluate(self, case: Case, output: str) -> SkillResult:
        expected = [str(f).lower() for f in case.expected.get("deliverable_files", [])]
        out_lower = output.lower()
        hits = [f for f in expected if Path(f).name.lower() in out_lower
                or any(tok in out_lower for tok in _tokens(Path(f).name))]
        ok = len(hits) > 0
        return SkillResult(
            skill_id=self.skill_id,
            status="ok",
            score=1.0 if ok else 0.0,
            subscores={"deliverable_mentioned": 1.0 if ok else 0.0},
            reasons={"deliverable_mentioned":
                     f"output references: {hits}" if ok
                     else f"output does not mention any of {expected}"},
        )


def _tokens(name: str) -> list[str]:
    """['Sample v2.xlsx'] → ['sample', 'v2'] (skip extension)."""
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return [t for t in re.split(r"[^a-z0-9]+", stem.lower()) if len(t) >= 3]


def build_registry(enable_judge: bool = True):
    from agenteval import SkillRegistry
    from cases import load_tasks

    registry = SkillRegistry()
    registry.register(ArtifactPresenceSkill())
    if enable_judge:
        for task in load_tasks():
            skill = GDPValJudgeSkill(build_judge_backend(), task)
            skill.skill_id = f"gdpval_judge_{task['task_id'][:8]}"
            registry.register(skill)
    return registry


def build_router(registry: "agenteval.SkillRegistry"):
    from agenteval import Plan, RuleRouter
    from cases import load_tasks

    task_by_id = {t["task_id"]: t for t in load_tasks()}

    def route(case: Case, catalog: list[dict]) -> Plan:
        judge_id = f"gdpval_judge_{case.case_id[:8]}"
        selected = [
            {"skill_id": "artifact_presence", "role": "observation",
             "reason": "output should reference the required deliverable",
             "parameters": {}},
            {"skill_id": judge_id, "role": "core",
             "reason": "score the output against the task's rubric items",
             "parameters": {}},
        ]
        return Plan(case_id=case.case_id, selected_skills=tuple(selected),
                    skipped_skills=())

    return RuleRouter(route)


SKILL_WEIGHTS = {"artifact_presence": 0.0, "gdpval_judge": 1.0}
