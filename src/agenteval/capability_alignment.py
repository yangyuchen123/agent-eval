"""Capability coverage alignment for rubric-set analysis.

The analyst maps rubric criteria to a small, fixed capability coordinate system.
It does not judge criterion satisfaction and must not consume Gold labels or
Judge predictions.
"""
from __future__ import annotations
import json
from typing import Any, Mapping

CAPABILITY_DEFINITIONS: dict[str, str] = {
    # Each definition is operational: it says what a rubric must be about to
    # receive the label.  It is deliberately not an assessment of whether the
    # agent demonstrated the capability.
    "repo_navigation": "Finding and moving through the relevant repository files, directories, or modules.",
    "context_inspection": "Reading relevant code, configuration, documentation, or prior outputs before deciding or acting.",
    "requirement_parsing": "Turning the task instructions and constraints into explicit requirements or checks.",
    "planning": "Choosing and ordering an execution approach before or during implementation.",
    "scope_control": "Keeping changes and actions within the requested scope and avoiding unrelated modifications.",
    "file_read_before_write": "Inspecting a target file or relevant context before modifying it.",
    "code_editing": "Making the requested code changes in the appropriate files.",
    "multi_file_integration": "Coordinating changes across multiple files, modules, or interfaces so they work together.",
    "type_system_reasoning": "Reasoning about types, annotations, interfaces, or static type constraints.",
    "implementation_design": "Selecting or applying the structural design needed to implement the requested behavior.",
    "tool_selection": "Choosing a tool or command that is suitable for the requested operation.",
    "tool_schema_compliance": "Using a tool according to its required arguments, schema, and invocation contract.",
    "tool_result_use": "Using actual tool outputs to determine or adapt subsequent actions.",
    "parallel_action_coordination": "Coordinating actions that run in parallel, including their dependencies and results.",
    "task_state_tracking": "Keeping track of what has been completed, remains pending, or has failed during execution.",
    "test_execution": "Running the relevant tests or test commands for the requested change.",
    "lint_build_validation": "Running or checking lint, typecheck, build, or equivalent static/packaging validation.",
    "artifact_verification": "Checking the resulting files or other deliverables against the task requirements.",
    "failure_recovery": "Recognizing execution failures and taking an appropriate corrective or recovery action.",
    "completion_reporting": "Accurately reporting the completed work, results, limitations, or remaining issues.",
    "communication_formatting": "Presenting the final response in the requested format and with the requested information.",
    "safety_constraint_following": "Following explicit safety, security, or prohibited-action constraints.",
    "dependency_management": "Managing required packages, dependencies, versions, or dependency-related changes.",
    "other": "A capability that is genuinely evaluated but cannot be represented by the listed capabilities; explain it explicitly.",
}

GDPVAL_CAPABILITY_DEFINITIONS: dict[str, str] = {
    "requirement_parsing": "识别 task 明确提出的交付要求、约束和验收条件；不判断是否完成。",
    "artifact_creation": "创建并交付 task 要求的目标 artifact 本身，例如生成要求的 workbook、报告、演示文稿或代码文件；不表示 artifact 的具体内容、格式、公式或质量。",
    "spreadsheet_structure": "组织 spreadsheet 的工作表、行列、区域和布局结构，使其承载 task 要求的信息；不表示公式数值是否正确。",
    "formula_design": "设计或配置 spreadsheet 中的公式、引用和计算逻辑；不表示最终数值是否已经核对正确。",
    "financial_calculation": "根据财务规则、输入和期间进行金额、余额、折旧或其它财务数值计算；不表示展示格式。",
    "source_data_extraction": "从给定源文件、表格、记录或材料中识别并提取 task 所需的数据。",
    "reconciliation": "将两个或多个数据源、表格、期间或汇总结果进行核对、对应并解释差异。",
    "monthly_schedule_reasoning": "按月或按期间推导、排列和维护时间序列 schedule 中的业务关系。",
    "account_classification": "依据 task 或领域规则将项目、交易或账户归入适当类别。",
    "file_format_compliance": "使交付文件满足要求的文件类型、命名、可打开性或格式契约；不表示文件内容本身正确。",
    "artifact_validation": "对最终 artifact 进行检查或验证，以发现其是否满足要求；不等同于某个具体业务计算或格式设计。",
    "numeric_precision": "控制数值的精度、舍入、显示位数或数值一致性；不等同于完成完整财务计算。",
    "cross_sheet_integration": "在多个 worksheet 或 artifact 部分之间建立并保持正确的引用、联动或一致关系。",
    "presentation_formatting": "控制 artifact 的视觉呈现、格式、样式、可读性或版式。",
    "comment_annotation": "在 artifact 中添加要求的注释、说明、批注或来源标记。",
    "completion_reporting": "报告交付物已生成、包含什么、验证了什么以及仍有哪些限制；不等同于创建 artifact。",
    "other": "当前 taxonomy 无法表示但 criterion 确实评价的能力；必须在 reason 中说明，不能作为宽泛兜底。",
}

GDPVAL_CAPABILITIES = list(GDPVAL_CAPABILITY_DEFINITIONS)

CAPABILITIES = [
    "repo_navigation", "context_inspection", "requirement_parsing", "planning",
    "scope_control", "file_read_before_write", "code_editing", "multi_file_integration",
    "type_system_reasoning", "implementation_design", "tool_selection", "tool_schema_compliance",
    "tool_result_use", "parallel_action_coordination", "task_state_tracking", "test_execution",
    "lint_build_validation", "artifact_verification", "failure_recovery", "completion_reporting",
    "communication_formatting", "safety_constraint_following", "dependency_management", "other",
]


def capability_prompt(task: str, trace: str, rubric: list[Mapping[str, Any]], rubric_set: str, *, frozen_task_required: list[str] | None = None, frozen_trace_observed: list[str] | None = None, capability_definitions: Mapping[str, str] | None = None) -> list[dict[str, str]]:
    definitions = dict(capability_definitions or CAPABILITY_DEFINITIONS)
    allowed_capabilities = list(definitions)
    payload = {
        "task": task,
        "runtrace": trace,
        "rubric_set": rubric_set,
        "rubric_criteria": [{"criterion_id": str(x.get("criterion_id") or x.get("check_id")), "criterion": str(x.get("criterion") or x.get("description"))} for x in rubric],
        "allowed_capabilities": allowed_capabilities,
        "capability_definitions": definitions,
    }
    if frozen_task_required is not None:
        payload["frozen_task_required_capabilities"] = frozen_task_required
        payload["frozen_trace_observed_capabilities"] = frozen_trace_observed or []
    system = """You are CapabilityCoverageAlignmentAnalyst. Map evaluation rubrics to a fixed capability coordinate system.

ROLE BOUNDARY
- Describe what the task requires, what the trace makes observable, and what each rubric evaluates.
- Do NOT judge whether the agent satisfied any criterion.
- Do NOT output Gold labels, scores, accuracy, predictions, or an agent capability score.
- Capability taxonomy is only a measurement coordinate system, not human-intent ground truth.

MAPPING RULES
- Use the supplied capability definitions, not the capability names alone.
- Prefer the narrowest capability whose definition matches the criterion's central concern.
- Use exactly one primary capability and at most two secondary capabilities per criterion.
- A secondary capability must represent a genuinely independent concern in the wording; do not add related capabilities just because they appear in the task or trace.
- Do not map a criterion to a capability merely because the trace contains a related event.
- Keep rubric_evaluated, task_required, and trace_observed separate.
- If evidence is insufficient, use unknown rather than guessing.
- If frozen capability sets are supplied, copy them exactly instead of recomputing them.

FIELD GLOSSARY
- task_required_capabilities: capability atoms explicitly required by the task or necessary to produce the requested result; this is not a judgment of execution.
- trace_observed_capabilities: capability atoms for which the supplied trace contains observable agent behavior; this is not a judgment that the behavior was correct.
- criterion_mappings: one record for every input criterion, describing the capability or capabilities that criterion evaluates.
- criterion_id: copy the input identifier exactly.
- primary_capability: the single narrowest capability representing the criterion's main evaluation concern.
- secondary_capabilities: optional supporting capability concerns that are independently present in the same criterion.
- criterion_scope: the evaluation target category: task_outcome, agent_process, tool_policy, validation, communication, safety, or other.
- task_required: whether this criterion's mapped capability is required by the current task.
- trace_observed: whether the mapped capability is observable in the supplied trace, independent of satisfaction.
- trace_observability: observed means clear evidence exists; partial means only incomplete/indirect evidence exists; not_observed means no relevant trace evidence was found; unknown means the supplied trace cannot establish this.
- confidence: confidence in the mapping itself, not confidence that the agent satisfied the criterion.

Return only JSON."""
    user = f"""Input:\n{json.dumps(payload, ensure_ascii=False)}\n\nReturn exactly:\n{{\"task_required_capabilities\":[\"...\"],\"trace_observed_capabilities\":[\"...\"],\"criterion_mappings\":[{{\"criterion_id\":\"...\",\"primary_capability\":\"...\",\"secondary_capabilities\":[],\"criterion_scope\":\"task_outcome|agent_process|tool_policy|validation|communication|safety|other\",\"task_required\":true,\"trace_observed\":true,\"trace_observability\":\"observed|partial|not_observed|unknown\",\"confidence\":\"high|medium|low\"}}]}}\n\nEvery input criterion must occur exactly once. Use only allowed capability IDs and the supplied definitions. The mapping describes what the rubric evaluates, never whether it is satisfied."""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
