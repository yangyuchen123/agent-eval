"""Read-only adapter for persisted Harbor trial directories.

The adapter consumes Harbor's stable on-disk trial contract without importing
Harbor or eval-system.  Runtime-specific evidence remains behind portable
``trace_ref``/``artifact_ref`` values for the independent Judge service.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .contracts import AgentIdentity, ArtifactRef, ConversationTurn, EvalSample, ToolCall


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _trial_dir(path: Path) -> bool:
    return path.is_dir() and (path / "result.json").is_file() and (path / "trial.log").is_file()


def _sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _artifact_refs(trial: Path) -> tuple[ArtifactRef, ...]:
    root = trial / "artifacts"
    if not root.is_dir():
        return ()
    result: list[ArtifactRef] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "manifest.json"):
        rel = path.relative_to(root).as_posix()
        result.append(ArtifactRef(
            path=rel,
            media_type="application/json" if path.suffix.lower() == ".json" else "text/plain",
            sha256=_sha256(path),
            size_bytes=path.stat().st_size,
            role="final_output" if path.name in {"final_output.json", "answer.txt", "report.md"} else "artifact",
        ))
    return tuple(result)


def _primary_output(trial: Path, artifacts: tuple[ArtifactRef, ...]) -> str:
    root = trial / "artifacts"
    preferred = [
        "logs/artifacts/final_output.json",
        "logs/artifacts/answer.txt",
        "logs/artifacts/report.md",
        "output.txt",
    ]
    by_path = {item.path: item for item in artifacts}
    ordered = [by_path[p] for p in preferred if p in by_path]
    ordered += [item for item in artifacts if item not in ordered]
    for item in ordered:
        path = root / item.path
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return ""


def _conversation(trajectory: dict[str, Any]) -> tuple[ConversationTurn, ...]:
    turns: list[ConversationTurn] = []
    for index, step in enumerate(trajectory.get("steps") or [], 1):
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("step_id") or index)
        observations = {
            str(row.get("source_call_id") or ""): row.get("content")
            for row in ((step.get("observation") or {}).get("results") or [])
            if isinstance(row, dict)
        }
        calls = tuple(ToolCall(
            call_id=str(call.get("tool_call_id") or ""),
            name=str(call.get("function_name") or ""),
            arguments=call.get("arguments"),
            result=observations.get(str(call.get("tool_call_id") or "")),
            turn_id=step_id,
            status="ok",
        ) for call in (step.get("tool_calls") or []) if isinstance(call, dict))
        turns.append(ConversationTurn(
            turn_id=step_id,
            role=str(step.get("source") or "unknown"),
            content=str(step.get("message")) if step.get("message") is not None else None,
            tool_calls=calls,
            timestamp=step.get("timestamp"),
        ))
    return tuple(turns)


class HarborAdapter:
    """Normalize one Harbor trial, job directory, or jobs tree."""

    name = "harbor"
    definition_version = "agenteval.harbor-adapter.v1"

    def __init__(self, root: str | Path, *, include_failed: bool = True):
        self.root = Path(root).expanduser().resolve()
        self.include_failed = include_failed

    def discover_trial_dirs(self) -> list[Path]:
        if _trial_dir(self.root):
            return [self.root]
        if not self.root.is_dir():
            return []
        return sorted(path for path in self.root.rglob("*") if _trial_dir(path))

    def iter_samples(self) -> list[EvalSample]:
        samples: list[EvalSample] = []
        for trial in self.discover_trial_dirs():
            result = _read_json(trial / "result.json")
            failed = bool(result.get("exception_info"))
            if failed and not self.include_failed:
                continue
            task_spec = _read_json(trial / "specs" / "task.json")
            config = _read_json(trial / "config.json")
            trajectory = _read_json(trial / "agent" / "trajectory.json")
            artifacts = _artifact_refs(trial)
            task_id = str(task_spec.get("task_id") or result.get("task_name") or trial.name)
            instruction = str(task_spec.get("instruction") or "")
            if not instruction:
                task_path = ((config.get("task") or {}).get("path"))
                if task_path:
                    instruction_file = Path(str(task_path)).expanduser() / "instruction.md"
                    if instruction_file.is_file():
                        instruction = instruction_file.read_text(encoding="utf-8", errors="replace")
            agent_info = result.get("agent_info") or {}
            model_info = agent_info.get("model_info") or {}
            artifact_root = trial / "artifacts"
            trace_ref = {
                "scheme": "harbor",
                "trial_dir": str(trial),
                "trajectory_path": str(trial / "agent" / "trajectory.json"),
            }
            artifact_ref = {
                "scheme": "harbor",
                "trial_dir": str(trial),
                "artifacts_root": str(artifact_root),
                "paths": [item.path for item in artifacts],
            }
            samples.append(EvalSample(
                sample_id=trial.name,
                task_id=task_id,
                task=instruction or task_id,
                output=_primary_output(trial, artifacts),
                expected={},
                metadata={
                    "task_id": task_id,
                    "task_name": result.get("task_name"),
                    "task_checksum": result.get("task_checksum"),
                    "trial_uri": result.get("trial_uri"),
                    "adapter_version": self.definition_version,
                },
                context={
                    "trace_ref": trace_ref,
                    "artifact_ref": artifact_ref,
                    "trial_dir": str(trial),
                },
                agent=AgentIdentity(
                    name=str(agent_info.get("name") or "unknown"),
                    model=model_info.get("name"),
                    version=agent_info.get("version"),
                    provider=model_info.get("provider"),
                ),
                backend=self.name,
                run_id=trial.parent.name,
                attempt_id=str(result.get("id") or trial.name),
                status="failed" if failed else "completed",
                artifacts=artifacts,
                conversation=_conversation(trajectory),
                runtime_result={
                    # Deliberately excludes verifier_result/rewards in judge-only mode.
                    "status": "failed" if failed else "completed",
                    "exception_info": result.get("exception_info"),
                    "started_at": result.get("started_at"),
                    "finished_at": result.get("finished_at"),
                    "agent_result": result.get("agent_result"),
                },
                environment={"runtime": "harbor", "trial_dir": str(trial)},
            ))
        ids = [sample.sample_id for sample in samples]
        if len(ids) != len(set(ids)):
            raise ValueError("Harbor trials contain duplicate sample ids")
        return samples
