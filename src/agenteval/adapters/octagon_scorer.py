"""Bridge AgentOctagon environment scorers into AgentEval results."""
from __future__ import annotations

import hashlib
import json
import importlib.util
import inspect
import re
from pathlib import Path
from typing import Any

from ..backends import LLMBackend
from ..protocols import Case, SkillResult
from ..rubrics import Rubric
from ..rubric_planner import RubricPlanner
from ..preferences import MetaRubric
from ..skills.base import LLMSkill, RuleSkill
from .contracts import EvalSample
from .runtime_evidence import RuntimeEvidenceIndex


class OctagonScorerError(RuntimeError):
    """The environment scorer could not be loaded or returned invalid data."""


def _load_module(path: Path):
    name = "agenteval_octagon_scorer_" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise OctagonScorerError(f"cannot load scorer module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _meta(path: Path) -> dict[str, Any]:
    """Read the scorer-affecting meta subset without requiring PyYAML."""
    result: dict[str, Any] = {"name": path.parent.name, "dimensions": []}
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
    if yaml is not None:
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(value, dict):
                return value
        except Exception:
            pass
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^pass_threshold:\s*([0-9.]+)\s*$", text, re.MULTILINE)
    if match:
        result["pass_threshold"] = float(match.group(1))
    dimensions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        name_match = re.match(r"^\s*-\s+name:\s*([^#]+)", line)
        if name_match:
            current = {"name": name_match.group(1).strip().strip('"\'')}
            dimensions.append(current)
            continue
        weight_match = re.match(r"^\s+weight:\s*([0-9.]+)", line)
        if weight_match and current is not None:
            current["weight"] = float(weight_match.group(1))
    result["dimensions"] = dimensions
    return result


def _aggregate(scores: list[dict[str, Any]], meta: dict[str, Any]) -> float | None:
    values: list[tuple[str, float]] = []
    for item in scores:
        try:
            value = float(item.get("value", 0))
        except (TypeError, ValueError):
            raise OctagonScorerError(f"invalid scorer value: {item!r}")
        dimension = str(item.get("dimension") or "")
        values.append((dimension, value))
    if not values:
        return None
    # Octagon's scorer contract is 0..100. Keep support for a normalized
    # scorer returning 0..1 so the bridge can be used with migrated envs.
    scale = 100.0 if max(abs(value) for _, value in values) > 1.0 else 1.0
    weights = {
        str(item.get("name")): float(item.get("weight", 0))
        for item in meta.get("dimensions", [])
        if isinstance(item, dict) and item.get("name") is not None
    }
    weighted = [(value / scale, weights.get(dimension, 0.0)) for dimension, value in values]
    total_weight = sum(weight for _, weight in weighted if weight > 0)
    if total_weight > 0:
        return round(sum(value * weight for value, weight in weighted if weight > 0) / total_weight, 6)
    return round(sum(value for value, _ in weighted) / len(weighted), 6)


class OctagonScorerBridge:
    """Load and invoke one ``envs/<env>/scorer.py`` for a normalized sample."""

    skill_id = "octagon_environment_scorer"
    definition_version = "agenteval.octagon-scorer-bridge.v1"

    def __init__(self, env_root: str | Path):
        self.env_root = Path(env_root)

    def _paths(self, sample: EvalSample, env_name: str | None) -> tuple[Path, Path]:
        name = env_name or str(sample.environment.get("name") or sample.metadata.get("env_name") or "")
        if not name or Path(name).name != name:
            raise OctagonScorerError(f"invalid or missing environment name: {name!r}")
        env_dir = self.env_root / name
        scorer = env_dir / "scorer.py"
        if not scorer.is_file():
            raise OctagonScorerError(f"scorer.py not found for environment {name!r}")
        return env_dir, scorer

    def score(self, sample: EvalSample, *, env_name: str | None = None) -> SkillResult:
        env_dir, scorer_path = self._paths(sample, env_name)
        module = _load_module(scorer_path)
        scorer = getattr(module, "score", None)
        if not callable(scorer):
            raise OctagonScorerError(f"{scorer_path} does not define callable score()")

        attempt_dir = Path(str(sample.context.get("attempt_dir") or ""))
        env_db = attempt_dir / "env.db" if attempt_dir else None
        task = sample.context.get("task") or {
            "id": sample.task_id,
            "env_name": env_dir.name,
            "prompt": sample.task,
        }
        kwargs: dict[str, Any] = {
            "attempt_id": sample.attempt_id or sample.sample_id,
            "task": task,
            "env_db": env_db,
            "trace": sample.context.get("trace", []),
            "final_state": sample.context.get("final_state", {}),
            "events": sample.context.get("events", []),
        }
        try:
            signature = inspect.signature(scorer)
            accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
            if not accepts_kwargs:
                kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
            raw = scorer(**kwargs)
        except Exception as exc:
            raise OctagonScorerError(f"scorer failed for {env_dir.name}/{sample.sample_id}: {exc}") from exc
        if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
            raise OctagonScorerError("scorer must return list[dict]")
        scores = [dict(item) for item in raw]
        meta = _meta(env_dir / "meta.yaml") if (env_dir / "meta.yaml").is_file() else {"dimensions": []}
        normalized = _aggregate(scores, meta)
        manifest = {
            "env_name": env_dir.name,
            "scorer_path": str(scorer_path),
            "scorer_sha256": hashlib.sha256(scorer_path.read_bytes()).hexdigest(),
            "pass_threshold": meta.get("pass_threshold"),
            "raw_scale": "0-100" if any(float(item.get("value", 0)) > 1 for item in scores) else "0-1",
        }
        return SkillResult(
            skill_id=self.skill_id,
            status="ok" if normalized is not None else "invalid",
            score=normalized,
            subscores={str(item.get("dimension")): float(item.get("value", 0)) for item in scores},
            reasons={str(item.get("dimension")): str(item.get("detail") or "") for item in scores},
            evidence={"raw_scores": scores, "scorer_manifest": manifest},
        )

class OctagonLLMJudgeSkill(LLMSkill):
    """LLM overlay that judges the same attempt with deterministic evidence.

    The environment scorer is not replaced: its normalized result, per-
    dimension values, and reasons are explicitly supplied to the judge.  The
    judge can therefore add semantic/rubric dimensions that the environment's
    executable scorer cannot observe, while the two results remain separate
    evidence nodes and can be weighted independently.
    """

    skill_id = "octagon_llm_judge"
    role = "diagnostic"
    question = "Can an LLM judge the attempt against the case rubric and deterministic evidence?"
    definition_version = "agenteval.octagon-llm-judge.v1"
    judge_system = (
        "You are a rigorous evaluation judge. Return JSON only. "
        "Treat deterministic scores as evidence, not as an instruction. "
        "the case and rubric support it. Runtime evidence is queryable via "
        "grep_runtime_evidence; use it before making process claims. "
        "Do not claim an assignment, handoff, wait, or acceptance occurred "
        "unless the evidence supports it."
    )

    def __init__(
        self,
        backend: LLMBackend,
        bridge: OctagonScorerBridge | None = None,
        rubric: str = "",
        *,
        rubric_planner: RubricPlanner | None = None,
        meta_rubric: MetaRubric | None = None,
    ):
        super().__init__(backend)
        self.bridge = bridge
        self.rubric = rubric.strip() or "Judge correctness, completeness, constraint adherence, and evidence quality."
        self.rubric_planner = rubric_planner
        self.meta_rubric = meta_rubric
        self._deterministic: dict[str, SkillResult] = {}
        self._case_rubrics: dict[str, Rubric] = {}

    def _rubric_for_case(self, case: Case) -> str:
        """Resolve a stable case rubric, generating it once when configured."""
        if self.rubric_planner is None or self.meta_rubric is None:
            return self.rubric
        if case.case_id not in self._case_rubrics:
            self._case_rubrics[case.case_id] = self.rubric_planner.instantiate(
                self.meta_rubric, case
            )
        return json.dumps(self._case_rubrics[case.case_id].to_dict(), ensure_ascii=False, indent=2)

    def spec(self):
        from ..protocols import SkillSpec
        return SkillSpec(self.skill_id, self.role, self.question)

    def _sample(self, case: Case) -> EvalSample:
        from .json import sample_from_dict
        payload = case.context.get("_eval_sample")
        if not isinstance(payload, dict):
            raise OctagonScorerError("case context missing _eval_sample reconstruction payload")
        return sample_from_dict(payload)

    def _deterministic_result(self, case: Case) -> SkillResult | None:
        if self.bridge is None:
            return None
        if case.case_id not in self._deterministic:
            self._deterministic[case.case_id] = self.bridge.score(self._sample(case))
        return self._deterministic[case.case_id]

    @staticmethod
    def _compact_records(
        records: Any, *, limit: int = 80, text_limit: int = 3000
    ) -> list[dict[str, Any]]:
        """Preserve an auditable, bounded slice of runtime evidence.

        The old implementation kept only ``tool_name``/timestamps from trace
        records. That made the judge unable to see Agent prompts/results,
        file paths, errors, or tool-call identities, so it had to infer process
        quality from retrospective artifacts. Event streams are also much
        larger than trace streams; lifecycle and completed tool-result events
        are prioritized over token-delta noise.
        """
        if not isinstance(records, list):
            return []

        def kind(item: dict[str, Any]) -> str:
            return str(item.get("kind") or item.get("event") or "")

        priority_kinds = {
            "agent:start", "agent:end", "tool:result:done",
            "tool:result:error", "llm:response:done",
        }
        priority = [
            item for item in records
            if isinstance(item, dict) and kind(item) in priority_kinds
        ]
        ordinary = [item for item in records if isinstance(item, dict)]
        if len(priority) >= limit:
            selected = priority[:limit]
        else:
            remaining = limit - len(priority)
            if len(ordinary) <= remaining:
                selected = priority + ordinary
            else:
                head = ordinary[: remaining // 2]
                tail = ordinary[-(remaining - len(head)):]
                selected = priority + head + tail

        def clipped(value: Any) -> Any:
            if isinstance(value, str):
                return value[:text_limit] + ("\n[truncated]" if len(value) > text_limit else "")
            if isinstance(value, (dict, list, tuple)):
                text = json.dumps(value, ensure_ascii=False, default=str)
                return text[:text_limit] + ("\n[truncated]" if len(text) > text_limit else "")
            return value

        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in selected:
            record_kind = kind(item)
            raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
            payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
            function = payload.get("function") if isinstance(payload.get("function"), dict) else {}
            row: dict[str, Any] = {
                "kind": record_kind or None,
                "timestamp": item.get("timestamp"),
            }
            for key in (
                "tool_name", "tool_call_id", "attempt_id", "agent_id",
                "loop_name", "description", "file_path", "is_error",
                "duration_ms", "skill_origin",
            ):
                if item.get(key) is not None:
                    row[key] = clipped(item[key])
            # AgentOctagon event records put identity and lifecycle details
            # inside raw.payload rather than at the top level.
            for key in (
                "loop_name", "tool_call_id", "parent_fork_tool_call_id",
                "description", "ok", "error", "agent_id",
            ):
                if payload.get(key) is not None:
                    row[key] = clipped(payload[key])
            if function.get("name") is not None:
                row["function"] = clipped(function.get("name"))
            for key in ("arguments", "arguments_delta", "content", "result"):
                value = item.get(key)
                if value is None:
                    value = payload.get(key)
                if value is None and key == "content":
                    value = raw.get("content")
                if value is not None:
                    row[key] = clipped(value)
            # Avoid duplicate streamed event fragments while preserving one
            # representative record for each tool/lifecycle identity.
            identity = (
                record_kind,
                str(row.get("tool_call_id") or row.get("id") or row.get("function") or ""),
                str(row.get("timestamp") or ""),
            )
            if record_kind == "llm:tool_call:created" and row.get("arguments_delta") is not None:
                # Deltas are individually low-value; keep them only if there
                # is no completed trace record for this call.
                continue
            if identity in seen:
                continue
            seen.add(identity)
            result.append({k: v for k, v in row.items() if v is not None})
        return result

    @staticmethod
    def _agent_lifecycle(records: Any) -> list[dict[str, Any]]:
        """Extract all agent start/end events, independent of event sampling."""
        if not isinstance(records, list):
            return []
        result = []
        for item in records:
            if not isinstance(item, dict) or item.get("kind") not in {"agent:start", "agent:end"}:
                continue
            payload = ((item.get("raw") or {}).get("payload") or {})
            result.append({
                "kind": item.get("kind"),
                "timestamp": item.get("timestamp"),
                "loop_name": payload.get("loop_name"),
                "description": payload.get("description"),
                "parent_fork_tool_call_id": payload.get("parent_fork_tool_call_id"),
                "ok": payload.get("ok"),
                "error": payload.get("error"),
            })
        return result

    @staticmethod
    def _project_trajectory_steps(value: Any, *, limit: int = 180) -> list[dict[str, Any]]:
        """Project the runtime's logical trajectory schema without task semantics.

        This keeps the generic runtime fields needed to reconstruct order and
        correlation. It does not choose dimensions or concepts from any
        particular evaluation methodology.
        """
        steps = value.get("steps") if isinstance(value, dict) else value
        if not isinstance(steps, list):
            return []
        result_by_call = {
            str(row.get("tool_call_id")): row for row in steps
            if isinstance(row, dict) and row.get("kind") == "tool_result"
        }
        projected: list[dict[str, Any]] = []
        for row in steps:
            if not isinstance(row, dict):
                continue
            kind = row.get("kind")
            if kind == "tool_call":
                call_id = str(row.get("tool_call_id") or "")
                item = {
                    "sequence": row.get("sequence"),
                    "timestamp": row.get("timestamp"),
                    "agent_id": row.get("agent_id"),
                    "parent_agent_id": row.get("parent_agent_id"),
                    "kind": kind,
                    "tool_call_id": row.get("tool_call_id"),
                    "tool_name": row.get("tool_name"),
                    "logical_call_id": row.get("logical_call_id"),
                    "completed": call_id in result_by_call,
                }
                projected.append({k: v for k, v in item.items() if v is not None})
            elif kind == "assistant":
                projected.append({k: row.get(k) for k in
                                  ("sequence", "timestamp", "agent_id", "kind", "logical_call_id")
                                  if row.get(k) is not None})
        if len(projected) <= limit:
            return projected
        half = limit // 2
        return projected[:half] + projected[-(limit - half):]

    @staticmethod
    def _project_wire_records(records: Any, *, limit: int = 24) -> list[dict[str, Any]]:
        """Project normalized wire records using runtime-contract fields only."""
        if not isinstance(records, list):
            return []
        selected = records if len(records) <= limit else records[:limit // 2] + records[-(limit - limit // 2):]
        projected = []
        for row in selected:
            if not isinstance(row, dict):
                continue
            correlation = row.get("correlation") or {}
            time = row.get("time") or {}
            data = row.get("data") or {}
            response = data.get("response") or {}
            usage = data.get("usage") or {}
            item = {
                "record_type": row.get("record_type"),
                "phase": row.get("phase"),
                "timestamp": time.get("timestamp"),
                "finished_at": time.get("finished_at"),
                "correlation": {
                    k: correlation.get(k) for k in
                    ("agent_id", "parent_agent_id", "logical_call_id", "turn_id")
                    if correlation.get(k) is not None
                },
                "data": {
                    k: data.get(k) for k in
                    ("call_role", "model_resolved", "finish_reason")
                    if data.get(k) is not None
                },
                "response": {
                    k: response.get(k) for k in ("output_blocks",) if response.get(k) is not None
                },
                "usage": {
                    k: usage.get(k) for k in ("input_tokens", "output_tokens")
                    if usage.get(k) is not None
                },
            }
            item = {k: v for k, v in item.items() if v}
            projected.append(item)
        return projected

    @staticmethod
    def _workspace_files(sample: EvalSample, *, per_file_limit: int = 120_000, total_limit: int = 600_000) -> dict[str, str]:
        root_value = str(sample.context.get("workspace_root") or "").strip()
        if root_value:
            root = Path(root_value)
        else:
            attempt_dir_value = str(sample.context.get("attempt_dir") or "").strip()
            if not attempt_dir_value:
                return {}
            root = Path(attempt_dir_value) / "skill_workspace"
        if not root.is_dir():
            return {}
        result: dict[str, str] = {}
        total = 0
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = path.relative_to(root).as_posix()
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(content) > per_file_limit:
                content = content[:per_file_limit] + "\n[truncated]"
            if total + len(content) > total_limit:
                break
            result[rel] = content
            total += len(content)
        return result

    @staticmethod
    def _evidence_tools() -> list[dict[str, Any]]:
        return [{
            "type": "function",
            "function": {
                "name": "grep_runtime_evidence",
                "description": "Search semantic runtime evidence. Streaming delta records are excluded; matching records preserve tool arguments, completed results, messages, identities, and timestamps.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Regex or plain-text search pattern"},
                        "source": {"type": "string", "enum": ["trace.jsonl", "events.jsonl", "wire.jsonl"]},
                        "agent_id": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 30},
                    },
                    "required": ["pattern"],
                    "additionalProperties": False,
                },
            },
        }]

    def _evidence_index(self, case: Case) -> RuntimeEvidenceIndex:
        return RuntimeEvidenceIndex.from_sample_context(self._sample(case).context)

    def messages(self, case: Case, output: str) -> list[dict[str, Any]]:
        deterministic = self._deterministic_result(case)
        sample = self._sample(case)
        packet = {
            "rubric": self._rubric_for_case(case),
            "case": {"case_id": case.case_id, "task": case.task,
                     "expected": case.expected, "metadata": case.metadata},
            "agent_output": output,
            "conversation": [turn.to_dict() for turn in sample.conversation],
            "artifacts": [artifact.to_dict() for artifact in sample.artifacts],
            "workspace_files": self._workspace_files(sample),
            "runtrace": {
                "source": "runtime evidence index built from trajectory/wire/semantic records",
                "trajectory_steps": len((sample.context.get("trajectory") or {}).get("steps", [])) if isinstance(sample.context.get("trajectory"), dict) else 0,
                "wire_records": len(sample.context.get("wire", [])) if isinstance(sample.context.get("wire"), list) else 0,
                "raw_trace_records": len(sample.context.get("raw_trace", [])) if isinstance(sample.context.get("raw_trace"), list) else 0,
                "raw_event_records": len(sample.context.get("raw_events", [])) if isinstance(sample.context.get("raw_events"), list) else 0,
                "evidence_manifest": self._evidence_index(case).manifest(),
                "access": "Use grep_runtime_evidence instead of assuming facts from the manifest.",
            },
            "final_state": sample.context.get("final_state", {}),
            "runtime_result": sample.runtime_result,
            "deterministic_environment_score": deterministic.to_dict() if deterministic else None,
            "required_response_schema": {
                "score": "number in [0,1]",
                "subscores": "object of dimension -> number in [0,1]",
                "reasons": "object of dimension -> concise explanation",
                "additive_findings": "array of findings not captured by deterministic scorer",
                "confidence": "number in [0,1]"
            },
        }
        return [{"role": "system", "content": self.judge_system},
                {"role": "user", "content": json.dumps(packet, ensure_ascii=False, indent=2)}]

    def evaluate(self, case: Case, output: str) -> SkillResult:
        messages = self.messages(case, output)
        index = self._evidence_index(case)

        def handle(name: str, args: dict[str, Any]) -> dict[str, Any]:
            if name != "grep_runtime_evidence":
                return {"error": f"unknown tool: {name}"}
            try:
                return index.grep(**args)
            except (TypeError, ValueError) as exc:
                return {"error": str(exc)}

        # Keep compatibility with test/dry-run backends that replace infer on
        # an instance. Normal LLMBackend instances use the real tool loop.
        infer_override = getattr(self.backend.infer, "__self__", None) is not self.backend
        if infer_override:
            response = self.backend.infer(messages)
        else:
            response = self.backend.infer_with_tools(
                messages, tools=self._evidence_tools(), tool_handler=handle, max_rounds=8
            )
        result = self.parse(response["parsed"], case)
        result.diagnostics["judge"] = {
            "model": self.backend.model,
            "backend_digest": self.backend.config_digest,
            "provenance": response.get("response_metadata", {}),
        }
        result.diagnostics["judge_prompt"] = {
            "system": self.judge_system,
            "user": messages[-1]["content"],
            "evidence_access": "grep_runtime_evidence",
        }
        result.evidence["evidence_manifest"] = index.manifest()
        result.evidence["evidence_queries"] = response.get("response_metadata", {}).get("tool_calls", [])
        return result

    def parse(self, parsed: dict[str, Any], case: Case) -> SkillResult:
        def number(value: Any, name: str) -> float:
            try:
                result = float(value)
            except (TypeError, ValueError) as exc:
                raise OctagonScorerError(f"LLM judge {name} must be numeric") from exc
            if not 0 <= result <= 1:
                raise OctagonScorerError(f"LLM judge {name} must be in [0,1], got {result}")
            return round(result, 6)

        score = number(parsed.get("score"), "score")
        raw_subscores = parsed.get("subscores") or {}
        if not isinstance(raw_subscores, dict):
            raise OctagonScorerError("LLM judge subscores must be an object")
        subscores = {str(k): number(v, f"subscores[{k}]") for k, v in raw_subscores.items()}
        raw_reasons = parsed.get("reasons") or {}
        if not isinstance(raw_reasons, dict):
            raise OctagonScorerError("LLM judge reasons must be an object")
        reasons = {str(k): str(v) for k, v in raw_reasons.items()}
        deterministic = self._deterministic_result(case)
        return SkillResult(
            skill_id=self.skill_id, status="ok", score=score,
            subscores=subscores, reasons=reasons,
            evidence={
                "rubric": self._rubric_for_case(case),
                "rubric_provenance": (self._case_rubrics.get(case.case_id).provenance if case.case_id in self._case_rubrics else None),
                "meta_rubric": self.meta_rubric.to_dict() if self.meta_rubric else None,
                "deterministic_environment_score": deterministic.to_dict() if deterministic else None,
                "additive_findings": parsed.get("additive_findings", []),
            },
            diagnostics={"confidence": parsed.get("confidence")},
        )


class OctagonEnvironmentSkill(RuleSkill):
    """AgentEval skill wrapper around an Octagon environment scorer."""

    skill_id = "octagon_environment_scorer"
    role = "core"
    question = "Does the AgentOctagon environment scorer accept the final attempt state?"
    definition_version = "agenteval.octagon-environment-scorer.v1"

    def __init__(self, bridge: OctagonScorerBridge):
        self.bridge = bridge

    def spec(self):
        from ..protocols import SkillSpec
        return SkillSpec(self.skill_id, self.role, self.question)

    def prepare(self, case, output):
        return None

    def evaluate(self, case, output):
        from .json import sample_from_dict
        payload = case.context.get("_eval_sample")
        if not isinstance(payload, dict):
            raise OctagonScorerError("case context missing _eval_sample reconstruction payload")
        return self.bridge.score(sample_from_dict(payload))


def score_octagon_samples(
    samples: list[EvalSample],
    *,
    env_root: str | Path,
    run_root: str | Path,
    model_id: str = "unknown",
    plan_root: str | Path | None = None,
    judge_backend: LLMBackend | None = None,
    judge_rubric: str = "",
    deterministic_weight: float = 1.0,
    judge_weight: float = 0.0,
    judge_only: bool = False,
    rubric_planner: RubricPlanner | None = None,
    meta_rubric: MetaRubric | None = None,
):
    """Run the normal AgentEval evidence/report pipeline on Octagon samples."""
    from ..planner import RuleRouter
    from ..protocols import Plan
    from ..runner import RunConfig, run_eval, write_evidence
    from ..report import build_report, write_report_artifacts
    from ..score import dataset_summary, weighted_case_score
    from ..skills.registry import SkillRegistry

    bridge = OctagonScorerBridge(env_root)
    registry = SkillRegistry()
    skill = None
    if not judge_only:
        skill = OctagonEnvironmentSkill(bridge)
        registry.register(skill)
    judge_skill = None
    if judge_backend is not None:
        judge_skill = OctagonLLMJudgeSkill(
            judge_backend, None if judge_only else bridge, judge_rubric,
            rubric_planner=rubric_planner, meta_rubric=meta_rubric,
        )
        registry.register(judge_skill)
    if judge_only and judge_backend is None:
        raise ValueError("judge_only requires judge_backend")
    if (rubric_planner is None) != (meta_rubric is None):
        raise ValueError("rubric_planner and meta_rubric must be provided together")
    if deterministic_weight < 0 or judge_weight < 0 or (
        judge_backend is not None and deterministic_weight + judge_weight <= 0
    ):
        raise ValueError("skill weights must be non-negative and not both zero")

    def route(case, catalog):
        selected = []
        if skill is not None:
            selected.append({
                "skill_id": skill.skill_id,
                "role": "core",
                "reason": "use the selected AgentOctagon environment scorer",
                "parameters": {},
            })
        if judge_skill is not None:
            selected.append({
                "skill_id": judge_skill.skill_id,
                "role": "diagnostic",
                "reason": "judge the case with deterministic scorer evidence and the configured rubric",
                "parameters": {},
            })
        return Plan(
            case_id=case.case_id,
            selected_skills=tuple(selected),
            skipped_skills=(),
            routing_mode="rule",
            planner={"backend": "agent-octagon"},
        )

    router = RuleRouter(route)
    config = RunConfig(
        router=router,
        registry=registry,
        run_root=Path(run_root),
        plan_root=Path(plan_root) if plan_root else None,
        model_id=model_id,
        agent_name="agent-octagon",
        benchmarks=("agent-octagon",),
    )
    cases = [sample.to_case() for sample in samples]
    outputs = {sample.sample_id: sample.output for sample in samples}
    report = run_eval(config, cases, outputs)
    write_evidence(config.run_root, report)
    weights = {}
    if skill is not None:
        weights[skill.skill_id] = deterministic_weight
    if judge_skill is not None:
        weights[judge_skill.skill_id] = judge_weight
    case_scores = {
        case_id: weighted_case_score(evidence, weights)
        for case_id, evidence in report.evidence.items()
    }
    summary = dataset_summary(list(report.evidence.values()), case_scores, weights)
    final = build_report(
        list(report.evidence.values()), case_scores, summary,
        model_id=model_id,
        aggregator_name="weighted_case_score",
    )
    artifacts = write_report_artifacts(config.run_root, final)
    return report, artifacts
