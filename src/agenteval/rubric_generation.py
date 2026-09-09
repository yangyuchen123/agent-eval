"""Minimal RuVer human-rubric memory and retrieval utilities.

This module intentionally stops before rubric generation.  It freezes task-level
human rubric examples and produces leakage-safe retrieval review packets for the
MVP gate described in ``docs/RUBRIC_GENERATION_PIPELINE_PLAN_2026-09-01.md``.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_MEMORY = "agenteval.ruver_rubric_memory.v1"
SCHEMA_RETRIEVAL = "agenteval.ruver_retrieval_result.v1"
TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+#.-]*|[\u4e00-\u9fff]+")


def digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"expected object at {path}:{line_no}")
        rows.append(value)
    return rows


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(f"{k}: {_text(v)}" for k, v in value.items())
    return "" if value is None else str(value)


def _tokens(value: str) -> Counter[str]:
    return Counter(token.lower() for token in TOKEN_RE.findall(value))


def _checklist(case: Mapping[str, Any], labels: Mapping[str, Any]) -> list[dict[str, Any]]:
    instance_id = str(case["instance_id"])
    label_case = labels.get(instance_id, {})
    result: list[dict[str, Any]] = []
    for category, group in (case.get("checklist") or {}).items():
        label_group = label_case.get(category, {}) if isinstance(label_case, dict) else {}
        label_items = {str(x.get("check_id")): x for x in label_group.get("checks", [])} if isinstance(label_group, dict) else {}
        for item in group.get("checks", []) if isinstance(group, dict) else []:
            criterion_id = str(item.get("check_id", ""))
            label = label_items.get(criterion_id, {}).get("result")
            result.append({
                "criterion_id": criterion_id,
                "category": str(category),
                "criterion": str(item.get("description", "")),
                "gold_label": label if label in {"success", "fail"} else None,
                "source_path": "agenticcoding_dataset.jsonl + agenticcoding_labels.json",
            })
    return result


def extract_task_features(case: Mapping[str, Any]) -> dict[str, Any]:
    """Extract only the stable MVP representation; never reads checklist."""
    task_text = _text(case.get("user_query"))
    environment = " ".join([
        _text(case.get("system_prompt")),
        _text(case.get("category")),
        _text(case.get("scaffold")),
        _text(case.get("image")),
        _text(case.get("workspace_abs_path")),
    ])
    all_text = f"{task_text}\n{environment}".lower()
    operations = {
        "edit_code": ["implement", "modify", "fix", "add", "change", "update", "refactor", "write code"],
        "search_repo": ["search", "find", "grep", "explore", "inspect codebase", "repository"],
        "run_tests": ["test", "pytest", "unit test", "tests"],
        "lint": ["lint", "ruff", "eslint", "format"],
        "typecheck": ["typecheck", "type check", "typescript", "mypy", "tsc"],
        "build": ["build", "compile", "bundle"],
        "manipulate_file": ["file", "json", "yaml", "csv", "pdf", "xlsx", "write", "read"],
        "integrate_module": ["integrat", "module", "api", "dependency", "interface"],
        "inspect_output": ["output", "result", "validate", "verify", "check"],
    }
    selected_ops = [name for name, terms in operations.items() if any(term in all_text for term in terms)]
    task_type = "other"
    for name, terms in {
        "bug_fix": ["bug", "fix", "issue", "error", "failure"],
        "feature_addition": ["implement", "add", "feature", "support"],
        "file_operation": ["file", "pdf", "xlsx", "csv", "json", "yaml"],
        "repo_understanding": ["understand", "explain", "explore", "investigate"],
        "refactor": ["refactor", "restructure", "rename"],
        "validation": ["validate", "verify", "test", "check"],
    }.items():
        if any(term in all_text for term in terms):
            task_type = name
            break
    artifact_type = []
    for value, terms in {
        "code": ["code", "module", "function", "typescript", "python", "javascript"],
        "tests": ["test", "pytest", "unit test"],
        "configuration": ["config", "yaml", "json", "toml"],
        "document": ["document", "markdown", "pdf"],
        "tabular_file": ["xlsx", "spreadsheet", "csv"],
    }.items():
        if any(term in all_text for term in terms):
            artifact_type.append(value)
    languages = [x for x in ("python", "typescript", "javascript", "java", "go", "rust", "bash", "sql") if x in all_text]
    tools = []
    for tool in ("bash", "shell", "git", "pytest", "ruff", "eslint", "mcp", "task", "subagent", "docker"):
        if tool in all_text:
            tools.append(tool)
    validations = [x for x in ("tests", "lint", "typecheck", "build", "verify", "validation") if x in all_text]
    integration = [x for x in ("module", "api", "dependency", "integration", "existing system", "interface") if x in all_text]
    return {
        "task_type": [task_type],
        "artifact_type": artifact_type,
        "language_or_framework": languages,
        "required_operations": selected_ops,
        "tool_environment": tools,
        "validation_requirements": validations,
        "integration_requirement": integration,
    }


def task_representation(case: Mapping[str, Any]) -> str:
    features = extract_task_features(case)
    return "\n".join([
        _text(case.get("user_query")),
        "task_type=" + ",".join(features["task_type"]),
        "artifact_type=" + ",".join(features["artifact_type"]),
        "language_or_framework=" + ",".join(features["language_or_framework"]),
        "required_operations=" + ",".join(features["required_operations"]),
        "tool_environment=" + ",".join(features["tool_environment"]),
        "validation_requirements=" + ",".join(features["validation_requirements"]),
        "integration_requirement=" + ",".join(features["integration_requirement"]),
    ])


def _git_commit(path: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def build_memory(dataset_path: str | Path, labels_path: str | Path, source_root: str | Path | None = None) -> list[dict[str, Any]]:
    cases = read_jsonl(dataset_path)
    raw_labels = json.loads(Path(labels_path).read_text(encoding="utf-8"))
    label_rows = raw_labels.get("results", []) if isinstance(raw_labels, dict) else raw_labels
    labels = {str(row.get("instance_id")): {k: v for k, v in row.items() if k != "instance_id"} for row in label_rows if isinstance(row, dict)}
    memory: list[dict[str, Any]] = []
    for case in cases:
        task_id = str(case["instance_id"])
        features = extract_task_features(case)
        rubrics = _checklist(case, labels)
        item = {
            "schema_version": SCHEMA_MEMORY,
            "memory_id": f"ruver-agenticcoding:{task_id}",
            "task_id": task_id,
            "task_text": _text(case.get("user_query")),
            "task_summary": _text(case.get("user_query"))[:500],
            "task_features": features,
            "human_rubrics": rubrics,
            "tool_environment": features["tool_environment"],
            "artifact_type": features["artifact_type"],
            "source": "ruverbench",
            "source_version": _git_commit(Path(source_root)) if source_root else None,
            "task_digest": digest({"task": case.get("user_query"), "metadata": {k: case.get(k) for k in ("category", "image", "scaffold", "workspace_abs_path")}}),
            "rubric_digest": digest(rubrics),
            "provenance_status": "aligned" if rubrics and all(x["gold_label"] is not None for x in rubrics) else "incomplete",
        }
        memory.append(item)
    return memory


def _feature_bonus(query: Mapping[str, Any], candidate: Mapping[str, Any]) -> tuple[float, list[str]]:
    q = query["task_features"]
    c = candidate["task_features"]
    matched: list[str] = []
    bonus = 0.0
    for key in ("task_type", "artifact_type", "language_or_framework", "required_operations", "tool_environment", "validation_requirements", "integration_requirement"):
        overlap = set(q.get(key, [])) & set(c.get(key, []))
        if overlap:
            matched.extend(f"{key}:{value}" for value in sorted(overlap))
            bonus += min(0.04, 0.01 * len(overlap))
    return bonus, matched


def _cosine(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    numerator = sum(a[x] * b[x] for x in common)
    denominator = math.sqrt(sum(x * x for x in a.values()) * sum(x * x for x in b.values()))
    return numerator / denominator if denominator else 0.0


def retrieve(query: Mapping[str, Any], memory: Iterable[Mapping[str, Any]], top_k: int = 5, excluded_task_ids: Iterable[str] = ()) -> list[dict[str, Any]]:
    excluded = {str(x) for x in excluded_task_ids}
    scored = []
    query_repr = task_representation(query)
    for item in memory:
        task_id = str(item["task_id"])
        if task_id in excluded:
            continue
        candidate_repr = "\n".join([
            str(item.get("task_text", "")),
            json.dumps(item.get("task_features", {}), ensure_ascii=False, sort_keys=True),
        ])
        semantic = _cosine(query_repr, candidate_repr)
        bonus, matched = _feature_bonus({"task_features": extract_task_features(query)}, item)
        scored.append((semantic + bonus, semantic, matched, item))
    scored.sort(key=lambda row: (-row[0], str(row[3]["task_id"])))
    results = []
    for rank, (score, semantic, matched, item) in enumerate(scored[:top_k], 1):
        results.append({
            "schema_version": SCHEMA_RETRIEVAL,
            "query_task_id": str(query["instance_id"]),
            "retrieved_task_id": str(item["task_id"]),
            "rank": rank,
            "retrieval_score": round(score, 8),
            "semantic_similarity": round(semantic, 8),
            "matched_features": matched,
            "human_rubrics": item.get("human_rubrics", []),
            "task_summary": item.get("task_summary", ""),
            "selection_method": "semantic+structured",
            "excluded_memory_ids": sorted(excluded),
            "review_label": None,
            "review_notes": "",
        })
    return results


def choose_queries(cases: list[dict[str, Any]], count: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    return sorted(rng.sample(cases, min(count, len(cases))), key=lambda x: str(x["instance_id"]))

GENERATOR_SCHEMA = "agenteval.generated_rubric.v1"


def build_global_profile(memory: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    memory = list(memory)
    families = Counter()
    examples: dict[str, list[str]] = {}
    for item in memory:
        for rubric in item.get("human_rubrics", []):
            category = str(rubric.get("category", "other"))
            family = {"User query": "outcome", "SP": "process_completion", "Agents.md": "integration", "Tool schema": "tool_policy", "System reminder": "safety_or_constraint", "Memory": "process_completion"}.get(category, "other")
            families[family] += 1
            examples.setdefault(family, []).append(str(rubric.get("criterion", "")))
    ordered = [name for name, _ in families.most_common()]
    return {
        "schema_version": "agenteval.ruver_global_rubric_profile.v1",
        "families": ordered,
        "family_counts": dict(families),
        "profile_text": "RuVer AgenticCoding commonly evaluates: " + ", ".join(ordered),
        "source_memory_task_count": len(memory),
    }


def generator_prompt(case: Mapping[str, Any], condition: str, demonstrations: list[Mapping[str, Any]], profile: Mapping[str, Any] | None = None, prompt_version: str = "v1_functional_scope") -> list[dict[str, str]]:
    features = extract_task_features(case)
    context = {
        "task_id": str(case["instance_id"]),
        "task": _text(case.get("user_query")),
        "features": features,
    }
    demo_text = []
    for item in demonstrations:
        demo_text.append(json.dumps({"task_id": item.get("task_id"), "task": item.get("task_summary"), "features": item.get("task_features"), "human_rubrics": item.get("human_rubrics")}, ensure_ascii=False))
    if condition == "task_only":
        source = "No human rubric examples are provided."
    elif condition == "global_profile":
        source = json.dumps(profile or {}, ensure_ascii=False)
    else:
        source = "\n".join(demo_text)
    if prompt_version in {"v2_ruver_scope_aligned", "v3_human_scope_explicit"}:
        system = """You generate a rubric for an AgenticCoding task that should reproduce the FULL scope of RuVer human evaluation, not only the task's functional outcome. RuVer human rubrics may evaluate both what the agent builds and how the agent operates: outcome, requirement coverage, integration, validation, process completion, planning, tool policy, TodoWrite/task-state behavior, read-before-write behavior, scope discipline, communication/style, safety, and system constraints. Treat the supplied human-rubric examples or global profile as evidence about what RuVer considers evaluable. For each recurring concern, explicitly decide whether it is applicable to the current task and observable in a future trajectory, artifact, state, or interaction record. In retrieved-example mode, do not omit applicable process/tool/policy concerns merely because the task text does not repeat them; transfer a pattern when the current task has the relevant agent interaction context. Still reject examples that are genuinely irrelevant or impossible to observe, and do not invent arbitrary preferences. Prefer atomic criteria, state applicability boundaries explicitly, and return only valid JSON."""
    else:
        system = """You generate a small, task-grounded rubric for an AgenticCoding task. Do not copy irrelevant examples. Only include criteria directly supported by the task or its environment and observable in a future agent trajectory/artifact. Prefer atomic criteria and avoid generic style criteria. Return only valid JSON."""
    user = f"""Current task:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\nReference material:\n{source}\n\nHuman examples/profile describe RuVer's evaluation scope. Use them to identify applicable agent-behavior concerns as well as task requirements. For retrieved examples, include a concern when the current task has the same relevant interaction or tool context, even if the exact wording is absent from the task. For task-only, do not claim knowledge of hidden human criteria. Do not generate Gold labels.\n\nReturn exactly this shape:\n{{\"criteria\":[{{\"criterion_id\":\"gen_001\",\"criterion\":\"...\",\"rubric_semantic_family\":\"outcome|requirement_coverage|integration|tool_policy|validation|process_completion|failure_handling|artifact_quality|style_or_communication|safety_or_constraint|other\",\"evidence_scope\":\"artifact|runtime|state|mixed\",\"source_basis\":[\"task_requirement\"],\"subrequirements\":[]}}]}}\nFor a compound criterion also include aggregation_rule. For a negative/absence criterion include absence_semantics. For vague words include boundary_notes or anchors. Do not invent Gold labels."""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def validate_generated(criteria: Any, case: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(criteria, list):
        return {"valid": False, "issues": [{"type": "invalid_criteria", "severity": "error"}], "recommended_action": "drop"}
    issues = []
    ids: set[str] = set()
    vague = {"frequent", "often", "properly", "appropriate", "reasonable", "concise", "consistent", "enough", "broad", "significant"}
    for item in criteria:
        if not isinstance(item, dict):
            issues.append({"type": "invalid_criterion", "severity": "error"}); continue
        cid = str(item.get("criterion_id", ""))
        text = str(item.get("criterion", ""))
        if cid in ids or not cid:
            issues.append({"type": "duplicate_criterion", "criterion_id": cid, "severity": "error"})
        ids.add(cid)
        lower = text.lower()
        if any(word in lower for word in vague) and not (item.get("boundary_notes") or item.get("anchors")):
            issues.append({"type": "vague_without_boundary", "criterion_id": cid, "severity": "warning"})
        if any(word in lower for word in ("does not", "do not", "never", "avoid", "without", "only")) and not item.get("absence_semantics"):
            issues.append({"type": "absence_without_semantics", "criterion_id": cid, "severity": "error"})
        if item.get("atomicity") == "compound" or len(item.get("subrequirements") or []) > 1:
            if not item.get("aggregation_rule"):
                issues.append({"type": "compound_without_aggregation", "criterion_id": cid, "severity": "error"})
        if not text.strip():
            issues.append({"type": "empty_criterion", "criterion_id": cid, "severity": "error"})
    errors = [x for x in issues if x.get("severity") == "error"]
    return {"valid": not errors, "issues": issues, "recommended_action": "accept" if not errors else "revise", "criterion_count": len(criteria)}


def blind_alignment_prompt(task: Mapping[str, Any], human: list[Mapping[str, Any]], systems: Mapping[str, list[Mapping[str, Any]]]) -> list[dict[str, str]]:
    payload = {
        "task_id": str(task["instance_id"]),
        "task": _text(task.get("user_query")),
        "human_rubrics": [{"id": str(x.get("criterion_id")), "criterion": str(x.get("criterion"))} for x in human],
        "systems": {name: [{"id": str(x.get("criterion_id")), "criterion": str(x.get("criterion")), "family": x.get("rubric_semantic_family"), "source_basis": x.get("source_basis", [])} for x in criteria] for name, criteria in systems.items()},
    }
    system = """You are a blind semantic alignment reviewer. Compare one task's human-authored rubric concerns with three anonymized generated rubric sets. Do not infer or mention which system is task-only, retrieved, or global-profile. Do not use Gold labels. Produce N:M semantic alignment, unsupported-extra judgments, and per-system granularity judgments. A generated criterion can be supported by the task even when absent from the human rubric. Do not judge whether the agent satisfied any criterion."""
    user = f"""Input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\nReturn only valid JSON with this shape:\n{{\"human_concern_count\":0,\"alignments\":[{{\"human_ids\":[\"H1\"],\"generated_refs\":[{{\"system\":\"System X\",\"ids\":[\"gen_001\"]}}],\"relation\":\"one_to_one|decomposition|merge|partial_overlap|missed_human\",\"coverage\":\"covered|partial|missed\",\"confidence\":\"high|medium|low\",\"reason\":\"...\"}}],\"generated_assessments\":{{\"System X\":[{{\"ids\":[\"gen_001\"],\"support\":\"task_supported|human_pattern_supported|unsupported|unclear\",\"granularity\":\"too_coarse|appropriate|too_fine\",\"retrieved_pattern_used\":\"true|false|partial|not_applicable\",\"reason\":\"...\"}}]}},\"notes\":\"...\"}}\nEvery human criterion must occur in exactly one alignment entry or be marked missed_human. Every generated criterion must be assessed exactly once under its system."""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
