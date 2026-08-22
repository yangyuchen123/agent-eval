"""GDPVal case package: real professional tasks (3 bundled instances).

GDPVal (openai/gdpval, 220 tasks across 9 sectors / 44 occupations) tests
whether an agent can produce a professional *deliverable file* (Excel,
Word, PDF...) meeting a human-written rubric. Each task carries its own
rubric — a list of discrete items {criterion, score}.

Mapping into AgentEval:
* Case.task     → the professional prompt (what the agent must produce)
* Case.expected → rubric items + deliverable file names
* skill         → GDPValJudgeSkill: a FineGrainedRubric built *per task*
  from its rubric items; aggregation is a weighted SUM (GDPVal total =
  Σ score of satisfied items, negative items are penalties).
* agent output  → the agent's deliverable as text (file-generation code,
  or a content report). A sandbox executor can be plugged in later; the
  judge works on textual evidence today.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agenteval import Case

CASES_FILE = Path(__file__).resolve().parent / "cases.json"


def load_tasks(path: Path = CASES_FILE) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases", data)
    if not isinstance(cases, list):
        raise ValueError(f"cases.json must contain a 'cases' array: {path}")
    return cases


def task_to_case(task: dict[str, Any]) -> Case:
    rubric_items = task["rubric_items"]
    return Case(
        case_id=task["task_id"],
        task=task["prompt"],
        expected={
            "occupation": task["occupation"],
            "sector": task["sector"],
            "deliverable_files": list(task.get("deliverable_files") or []),
            "rubric_items": rubric_items,
        },
        context={"task": task},
        metadata={
            "occupation": task["occupation"],
            "sector": task["sector"],
        },
    )


def load_cases(path: Path = CASES_FILE) -> list[Case]:
    return [task_to_case(t) for t in load_tasks(path)]
