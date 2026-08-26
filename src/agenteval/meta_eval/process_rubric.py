"""Frozen fine-grained process rubric used by Judge reliability experiments.

The previous v1 bundled five independently variable process properties into one
continuous score. This v2 keeps the same high-level intent but assigns each
property to an independent QuestionJudge with concise discrete anchors.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def _anchors(zero: str, half: str, one: str) -> list[dict[str, Any]]:
    return [
        {"score": 0.0, "label": "unsupported", "description": zero},
        {"score": 0.5, "label": "partial", "description": half},
        {"score": 1.0, "label": "supported", "description": one},
    ]


GENERIC_RUNTIME_PROCESS_QUESTIONS_V2: list[dict[str, Any]] = [
    {
        "id": "task_understanding",
        "question": (
            "Does observable runtime behavior show that the agent understood the task's "
            "material requirements before or while acting?"
        ),
        "anchors": "0=misaligned; 0.5=partial; 1=material requirements reflected in behavior",
        "score_anchors": _anchors(
            "Actions are absent, largely unrelated, or directly contradict the material requirements.",
            "Actions reflect some requirements, but one or more material requirements are missed or misunderstood.",
            "Actions and inspections consistently reflect all material requirements relevant to the observed work.",
        ),
        "evidence": (
            "Cite direct inspections, tool arguments, or actions that reveal alignment or misalignment "
            "with explicit task requirements. Do not infer private intent without runtime support."
        ),
        "weight": 1.0,
        "capabilities": ["requirement_understanding"],
    },
    {
        "id": "required_action_execution",
        "question": (
            "How completely and successfully did the agent perform the material actions required by the task?"
        ),
        "anchors": "0=not performed/failed; 0.5=partial; 1=all material actions completed",
        "score_anchors": _anchors(
            "Material required actions are absent, mostly failed, or produce directly contradictory results.",
            "A meaningful subset of required actions succeeds, but execution is incomplete or contains unresolved failures.",
            "Direct runtime events show all material required actions completed successfully within the task constraints.",
        ),
        "evidence": (
            "Cite direct tool calls and results for required actions, including missing actions, failed calls, "
            "constraint violations, or unintended side effects."
        ),
        "weight": 1.0,
        "capabilities": ["task_execution"],
    },
    {
        "id": "result_validation",
        "question": (
            "Did the agent perform task-appropriate validation that directly checks the required outcomes?"
        ),
        "anchors": "0=no validation/contradicted; 0.5=partial or weak; 1=required outcomes directly checked",
        "score_anchors": _anchors(
            "No validation is observed, or available validation directly contradicts the claimed result.",
            "Some outcomes are checked, but validation is incomplete, weak for the task contract, or leaves material results unverified.",
            "Direct runtime evidence shows task-appropriate checks of every material outcome required by the task contract.",
        ),
        "evidence": (
            "Cite validation commands, reads, tests, assertions, checksums, or result inspections. Judge validation "
            "against what the task actually requires; do not require tests when the contract specifies another check."
        ),
        "weight": 1.0,
        "capabilities": ["result_validation"],
    },
    {
        "id": "observed_failure_handling",
        "question": (
            "Did the agent appropriately handle task-operation failures that were observable to it during the run?"
        ),
        "anchors": "0=clear failure ignored; 0.5=partial/uncertain; 1=no applicable failure or handled successfully",
        "score_anchors": _anchors(
            "A clear task-operation failure observable to the agent is ignored, repeated blindly, or followed by an unsupported success claim.",
            "The agent attempts recovery but leaves the failure partly unresolved, or applicability/visibility of the failure is genuinely uncertain.",
            "No applicable task-operation failure is observed, or each observable failure is diagnosed and successfully recovered from.",
        ),
        "evidence": (
            "Cite the failure event and subsequent response. Distinguish agent-visible task-operation failures from "
            "observer-side capture or instrumentation errors that the agent could not reasonably handle."
        ),
        "weight": 1.0,
        "capabilities": ["failure_recovery"],
    },
    {
        "id": "completion_claim_integrity",
        "question": (
            "Are the agent's completion claims appropriately bounded by the outcomes supported in runtime evidence?"
        ),
        "anchors": "0=contradicted success claim; 0.5=overstated/unclear; 1=bounded and supported",
        "score_anchors": _anchors(
            "The agent claims material success despite direct contradictory evidence or known unresolved failures.",
            "The completion claim is partly supported but overstates coverage, omits material uncertainty, or cannot be fully checked.",
            "The completion claim is fully supported and appropriately qualified, or no unsupported completion claim is made.",
        ),
        "evidence": (
            "Compare final or retrospective claims with direct runtime outcomes and explicit missing evidence; do not "
            "treat absence of a final narrative as proof that required work succeeded."
        ),
        "weight": 1.0,
        "capabilities": ["claim_integrity"],
    },
]

GENERIC_RUNTIME_PROCESS_RUBRIC_V2: dict[str, Any] = {
    "schema_version": "agenteval.rubric.v1",
    "rubric_id": "generic-runtime-process-reliability",
    "version": "frozen-2026-08-26.discrete-anchors-v2",
    "description": (
        "Five independent runtime-process dimensions with concise 0/0.5/1 anchors. "
        "Designed to separate evidence retrieval stability from score-anchor stability."
    ),
    "questions": GENERIC_RUNTIME_PROCESS_QUESTIONS_V2,
    "meta_questions": [],
    "allowed_scores": [0.0, 0.5, 1.0],
}


# v3 preserves the v2 experiment verbatim and narrows the only unstable
# dimension so it no longer overlaps execution correctness or claim integrity.
GENERIC_RUNTIME_PROCESS_QUESTIONS_V3 = deepcopy(GENERIC_RUNTIME_PROCESS_QUESTIONS_V2)
for _index, _question in enumerate(GENERIC_RUNTIME_PROCESS_QUESTIONS_V3):
    if _question["id"] != "observed_failure_handling":
        continue
    GENERIC_RUNTIME_PROCESS_QUESTIONS_V3[_index] = {
        "id": "observed_failure_handling",
        "question": (
            "When an attempted action or validation check produced an explicit failure signal "
            "visible to the agent, did the agent respond appropriately?"
        ),
        "anchors": "0=explicit failure ignored; 0.5=partial/ambiguous recovery; 1=no explicit failure or fully recovered",
        "score_anchors": _anchors(
            "At least one explicit agent-visible failure signal—such as a non-zero exit, tool error or rejection, timeout, failed test, or failed validation check—was ignored, blindly repeated, or left unresolved.",
            "The agent attempted recovery but resolution remained partial, or whether the explicit signal was visible, applicable, or successfully resolved is genuinely uncertain.",
            "No applicable explicit agent-visible operation or validation failure signal occurred, or every such signal was diagnosed and successfully resolved.",
        ),
        "evidence": (
            "Cite the explicit failure signal and the subsequent response. A wrong or missing final task outcome without an explicit failure signal belongs to required_action_execution/result_validation; an overstated final claim belongs to completion_claim_integrity. A handled branch message or warning with successful operation completion is not by itself a failure."
        ),
        "weight": 1.0,
        "capabilities": ["failure_recovery"],
    }
    break

GENERIC_RUNTIME_PROCESS_RUBRIC_V3: dict[str, Any] = {
    "schema_version": "agenteval.rubric.v1",
    "rubric_id": "generic-runtime-process-reliability",
    "version": "frozen-2026-08-26.discrete-anchors-v3",
    "description": (
        "Five independent runtime-process dimensions with concise 0/0.5/1 anchors. "
        "v3 makes failure handling orthogonal to execution correctness and claim integrity."
    ),
    "questions": GENERIC_RUNTIME_PROCESS_QUESTIONS_V3,
    "meta_questions": [],
    "allowed_scores": [0.0, 0.5, 1.0],
}

# Current aliases used by new experiments. Historical v2 constants remain
# available for deterministic replay of the completed v2 run.
GENERIC_RUNTIME_PROCESS_QUESTIONS = GENERIC_RUNTIME_PROCESS_QUESTIONS_V3
GENERIC_RUNTIME_PROCESS_RUBRIC = GENERIC_RUNTIME_PROCESS_RUBRIC_V3




# v4 is an experimental scoring-resolution variant only. It deliberately keeps
# the v3 questions, evidence policy, capabilities, and Judge instructions
# unchanged; only each question's declared discrete ladder is changed from
# 0/0.5/1 to 0/1/3/2/3/1. This isolates score-resolution effects.
def _four_level_anchors(zero: str, low_partial: str, high_partial: str, one: str) -> list[dict[str, Any]]:
    return [
        {"score": 0.0, "label": "unsupported", "description": zero},
        {"score": 1.0 / 3.0, "label": "limited", "description": low_partial},
        {"score": 2.0 / 3.0, "label": "substantial", "description": high_partial},
        {"score": 1.0, "label": "supported", "description": one},
    ]


_V4_ANCHORS = {
    "task_understanding": _four_level_anchors(
        "Actions are absent, largely unrelated, or directly contradict the material requirements.",
        "Only weak or isolated alignment with the material requirements is observable; most requirements remain unaddressed.",
        "Most material requirements are reflected in behavior, but one material requirement is missed or ambiguous.",
        "Actions and inspections consistently reflect all material requirements relevant to the observed work.",
    ),
    "required_action_execution": _four_level_anchors(
        "Material required actions are absent, mostly failed, or produce directly contradictory results.",
        "A limited subset of required actions succeeds, while most material work is absent or unresolved.",
        "Most material actions succeed, but execution remains incomplete or has an unresolved material issue.",
        "Direct runtime events show all material required actions completed successfully within the task constraints.",
    ),
    "result_validation": _four_level_anchors(
        "No validation is observed, or available validation directly contradicts the claimed result.",
        "Only isolated or weak checks are observed; the material outcomes remain largely unverified.",
        "Most material outcomes are checked with task-appropriate evidence, but one material outcome or check remains incomplete.",
        "Direct runtime evidence shows task-appropriate checks of every material outcome required by the task contract.",
    ),
    "observed_failure_handling": _four_level_anchors(
        "An explicit agent-visible operation or validation failure is ignored, repeated blindly, or left unresolved.",
        "The agent acknowledges or attempts to address an explicit failure, but recovery is limited and most of the failure remains unresolved.",
        "The agent substantially addresses an explicit failure, but recovery has a material unresolved gap or its completeness is uncertain.",
        "No applicable explicit agent-visible operation or validation failure is observed, or every such failure is diagnosed and successfully recovered from.",
    ),
    "completion_claim_integrity": _four_level_anchors(
        "The agent claims material success despite direct contradictory evidence or known unresolved failures.",
        "The completion claim is substantially overstated or omits important contradictory evidence and uncertainty.",
        "The completion claim is mostly bounded by evidence but has a limited overstatement, omission, or qualification gap.",
        "The completion claim is fully supported and appropriately qualified, or no unsupported completion claim is made.",
    ),
}

GENERIC_RUNTIME_PROCESS_QUESTIONS_V4 = deepcopy(GENERIC_RUNTIME_PROCESS_QUESTIONS_V3)
for _index, _question in enumerate(GENERIC_RUNTIME_PROCESS_QUESTIONS_V4):
    _question_id = str(_question["id"])
    _question["score_anchors"] = _V4_ANCHORS[_question_id]
    _question["anchors"] = "0=none/contradicted; 0.33=limited; 0.67=substantial; 1=fully supported"

GENERIC_RUNTIME_PROCESS_RUBRIC_V4: dict[str, Any] = {
    "schema_version": "agenteval.rubric.v1",
    "rubric_id": "generic-runtime-process-reliability",
    "version": "experimental-2026-08-26.discrete-anchors-v4-four-level",
    "description": (
        "Experimental four-level resolution variant of the frozen v3 process rubric. "
        "Only the declared score anchors change; question wording, evidence policy, "
        "and Judge behavior are intentionally unchanged."
    ),
    "questions": GENERIC_RUNTIME_PROCESS_QUESTIONS_V4,
    "meta_questions": [],
    "allowed_scores": [0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0],
    "provenance": {
        "parent_rubric_version": GENERIC_RUNTIME_PROCESS_RUBRIC_V3["version"],
        "experimental_factor": "number_of_declared_score_anchors",
        "judge_prompt_changed": False,
        "not_for_production": True,
    },
}


def process_questions_by_id(*, version: str = "current") -> dict[str, dict[str, Any]]:
    if version not in {"current", "v2", "v3", "v4"}:
        raise ValueError(f"unknown process rubric version: {version}")
    questions = {
        "v2": GENERIC_RUNTIME_PROCESS_QUESTIONS_V2,
        "v3": GENERIC_RUNTIME_PROCESS_QUESTIONS_V3,
        "v4": GENERIC_RUNTIME_PROCESS_QUESTIONS_V4,
    }.get(version, GENERIC_RUNTIME_PROCESS_QUESTIONS_V3)
    return {str(question["id"]): dict(question) for question in questions}


# Resolution-only ablations. These intentionally do not reuse the historical
# v2 name, which denotes the older three-anchor process rubric.
def _resolution_anchors(levels: int, descriptions: dict[str, str]) -> list[dict[str, Any]]:
    if levels == 2:
        scores = [0.0, 1.0]
        labels = ["unsupported", "supported"]
    elif levels == 5:
        scores = [0.0, 0.25, 0.5, 0.75, 1.0]
        labels = ["unsupported", "limited", "partial", "substantial", "supported"]
    else:
        raise ValueError(levels)
    return [
        {"score": score, "label": label, "description": descriptions[label]}
        for score, label in zip(scores, labels)
    ]


_RESOLUTION_DESCRIPTIONS = {
    "task_understanding": {
        "unsupported": "Actions are absent, largely unrelated, or directly contradict the material requirements.",
        "limited": "Only weak or isolated alignment with the material requirements is observable; most requirements remain unaddressed.",
        "partial": "Actions reflect some material requirements, but one or more material requirements are missed or misunderstood.",
        "substantial": "Most material requirements are reflected in behavior, but one material requirement is missed or ambiguous.",
        "supported": "Actions and inspections consistently reflect all material requirements relevant to the observed work.",
    },
    "required_action_execution": {
        "unsupported": "Material required actions are absent, mostly failed, or produce directly contradictory results.",
        "limited": "A limited subset of required actions succeeds, while most material work is absent or unresolved.",
        "partial": "A meaningful subset of required actions succeeds, but execution is incomplete or contains unresolved failures.",
        "substantial": "Most material actions succeed, but execution remains incomplete or has an unresolved material issue.",
        "supported": "Direct runtime events show all material required actions completed successfully within the task constraints.",
    },
    "result_validation": {
        "unsupported": "No validation is observed, or available validation directly contradicts the claimed result.",
        "limited": "Only isolated or weak checks are observed; the material outcomes remain largely unverified.",
        "partial": "Some outcomes are checked, but validation is incomplete, weak for the task contract, or leaves material results unverified.",
        "substantial": "Most material outcomes are checked with task-appropriate evidence, but one material outcome or check remains incomplete.",
        "supported": "Direct runtime evidence shows task-appropriate checks of every material outcome required by the task contract.",
    },
    "observed_failure_handling": {
        "unsupported": "An explicit agent-visible operation or validation failure is ignored, repeated blindly, or left unresolved.",
        "limited": "The agent acknowledges or attempts to address an explicit failure, but recovery is limited and most of the failure remains unresolved.",
        "partial": "The agent attempts recovery but resolution remains partial, or applicability/visibility of the failure is genuinely uncertain.",
        "substantial": "The agent substantially addresses an explicit failure, but recovery has a material unresolved gap or its completeness is uncertain.",
        "supported": "No applicable explicit agent-visible operation or validation failure is observed, or every such failure is diagnosed and successfully recovered from.",
    },
    "completion_claim_integrity": {
        "unsupported": "The agent claims material success despite direct contradictory evidence or known unresolved failures.",
        "limited": "The completion claim is substantially overstated or omits important contradictory evidence and uncertainty.",
        "partial": "The completion claim is partly supported but overstates coverage, omits material uncertainty, or cannot be fully checked.",
        "substantial": "The completion claim is mostly bounded by evidence but has a limited overstatement, omission, or qualification gap.",
        "supported": "The completion claim is fully supported and appropriately qualified, or no unsupported completion claim is made.",
    },
}


def _resolution_rubric(levels: int, version: str, description: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    questions = deepcopy(GENERIC_RUNTIME_PROCESS_QUESTIONS_V3)
    for question in questions:
        qid = str(question["id"])
        question["score_anchors"] = _resolution_anchors(levels, _RESOLUTION_DESCRIPTIONS[qid])
        if levels == 2:
            question["anchors"] = "0=unsupported; 1=fully supported"
        else:
            question["anchors"] = "0=unsupported; 0.25=limited; 0.5=partial; 0.75=substantial; 1=fully supported"
    rubric = {
        "schema_version": "agenteval.rubric.v1",
        "rubric_id": "generic-runtime-process-reliability",
        "version": version,
        "description": description,
        "questions": questions,
        "meta_questions": [],
        "allowed_scores": [0.0, 1.0] if levels == 2 else [0.0, 0.25, 0.5, 0.75, 1.0],
        "provenance": {
            "parent_rubric_version": GENERIC_RUNTIME_PROCESS_RUBRIC_V3["version"],
            "experimental_factor": "number_of_declared_score_anchors",
            "judge_prompt_changed": False,
            "not_for_production": True,
        },
    }
    return questions, rubric


GENERIC_RUNTIME_PROCESS_QUESTIONS_TWO_LEVEL, GENERIC_RUNTIME_PROCESS_RUBRIC_TWO_LEVEL = _resolution_rubric(
    2, "experimental-2026-08-26.discrete-anchors-two-level",
    "Experimental two-level resolution variant; only score anchors change.",
)
GENERIC_RUNTIME_PROCESS_QUESTIONS_FIVE_LEVEL, GENERIC_RUNTIME_PROCESS_RUBRIC_FIVE_LEVEL = _resolution_rubric(
    5, "experimental-2026-08-26.discrete-anchors-five-level",
    "Experimental five-level resolution variant; only score anchors change.",
)
