"""SWE-bench case package: load instances → AgentEval cases.

The 2 bundled instances (sympy__sympy-20916, sympy__sympy-24443) are the
lightest in SWE-bench_Verified (fewest F2P/P2P tests, pure-Python deps),
so image builds and test runs stay fast. Add more instances to
`instances.json` — cases are just data.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agenteval import Case
from agenteval.protocols import Case as _Case  # noqa: F401  (re-export)

INSTANCES_FILE = Path(__file__).resolve().parent / "instances.json"


def load_instances(path: Path = INSTANCES_FILE) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    instances = data.get("instances", data)
    if not isinstance(instances, list):
        raise ValueError(f"instances.json must contain an 'instances' array: {path}")
    return instances


def instance_to_case(inst: dict[str, Any]) -> Case:
    """Map a SWE-bench instance to an AgentEval Case.

    * task     → problem_statement (what the agent sees)
    * expected → grading metadata (never shown to the agent)
    * context  → docker/repo info for skills
    """
    return Case(
        case_id=inst["instance_id"],
        task=inst["problem_statement"],
        expected={
            "repo": inst["repo"],
            "base_commit": inst["base_commit"],
            "test_patch": inst.get("test_patch", ""),
            "FAIL_TO_PASS": list(inst.get("FAIL_TO_PASS") or []),
            "PASS_TO_PASS": list(inst.get("PASS_TO_PASS") or []),
        },
        context={"instance": inst},
        metadata={
            "hints_text": inst.get("hints_text"),
            "gold_patch": inst.get("patch", ""),   # reference only, not for grading
        },
    )


def load_cases(path: Path = INSTANCES_FILE) -> list[Case]:
    return [instance_to_case(i) for i in load_instances(path)]
