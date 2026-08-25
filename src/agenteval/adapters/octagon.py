"""Read-only adapter for AgentOctagon persisted attempts.

The adapter intentionally does not import AgentOctagon backend modules. It reads
only the stable data contract: ``octagon.db`` plus an attempt directory. This
keeps scoring/runtime separation intact and lets the adapter work from archived
runs as well as a live data directory.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .contracts import (
    AgentIdentity,
    ArtifactRef,
    ConversationTurn,
    EvalSample,
    ToolCall,
)

_TEXT_NAMES = ("report.md", "answer.txt", "output.txt", "index.html", "README.md")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            rows.append({"_parse_error": True, "_line": line_no, "raw": line})
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_calls(trace: Iterable[dict[str, Any]]) -> tuple[ToolCall, ...]:
    calls: list[ToolCall] = []
    for index, row in enumerate(trace, 1):
        name = row.get("tool_name") or row.get("name")
        if not name:
            continue
        call_id = str(row.get("call_id") or row.get("id") or f"trace-{index}")
        calls.append(ToolCall(
            call_id=call_id,
            name=str(name),
            arguments=row.get("arguments") or row.get("input"),
            result=row.get("result") or row.get("output"),
            turn_id=row.get("turn_id"),
            status=str(row.get("status") or "ok"),
        ))
    return tuple(calls)


def _blade_history_conversation(attempt_dir: Path) -> tuple[ConversationTurn, ...]:
    payload = _read_json(attempt_dir / "blade_history.json")
    turns: list[ConversationTurn] = []
    for index, row in enumerate(payload.get("nodes", []), 1):
        if not isinstance(row, dict):
            continue
        calls: list[ToolCall] = []
        for call in row.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") or {}
            calls.append(ToolCall(
                call_id=str(call.get("id") or f"history-call-{index}"),
                name=str(function.get("name") or call.get("name") or ""),
                arguments=function.get("arguments") or call.get("arguments"),
                result=call.get("result"),
                status=str(call.get("status") or "ok"),
            ))
        turns.append(ConversationTurn(
            turn_id=str(row.get("id") or f"history-{index}"),
            role=str(row.get("role") or "unknown"),
            content=row.get("content") or row.get("preview"),
            tool_calls=tuple(calls),
            timestamp=row.get("timestamp"),
        ))
    return tuple(turns)


def _conversation(attempt_dir: Path) -> tuple[ConversationTurn, ...]:
    conversation = _jsonl(attempt_dir / "conversation.jsonl")
    trace = _jsonl(attempt_dir / "trace.jsonl")
    calls = _tool_calls(trace)
    by_turn: dict[str, list[ToolCall]] = {}
    for call in calls:
        if call.turn_id:
            by_turn.setdefault(call.turn_id, []).append(call)

    turns: list[ConversationTurn] = []
    for index, row in enumerate(conversation):
        event = str(row.get("event") or "")
        if event not in {"turn.started", "turn.completed", "turn.failed"}:
            continue
        turn_id = str(row.get("turn_id") or f"turn-{index + 1}")
        turns.append(ConversationTurn(
            turn_id=turn_id,
            role="system",
            content=row.get("purpose") or row.get("status") or event,
            tool_calls=tuple(by_turn.get(turn_id, ())),
            timestamp=row.get("timestamp"),
        ))

    # Legacy attempts may have no conversation event log. Keep trajectory
    # steps as a lossless, runtime-neutral fallback, then support the older
    # Blade history format used by many real Octagon attempts.
    if not turns:
        trajectory = _read_json(attempt_dir / "trajectory.json")
        for index, row in enumerate(trajectory.get("steps", []), 1):
            if not isinstance(row, dict):
                continue
            turns.append(ConversationTurn(
                turn_id=str(row.get("step_id") or f"step-{index}"),
                role=str(row.get("kind") or row.get("source") or "unknown"),
                content=row.get("content") or row.get("message") or row.get("text"),
                timestamp=row.get("timestamp"),
            ))
    if not turns:
        return _blade_history_conversation(attempt_dir)
    return tuple(turns)


def _artifacts(attempt_dir: Path) -> tuple[ArtifactRef, ...]:
    root = attempt_dir / "skill_workspace"
    if not root.is_dir():
        return ()
    result: list[ArtifactRef] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(attempt_dir).as_posix()
        result.append(ArtifactRef(
            path=rel,
            type="file",
            status="ok",
            size_bytes=path.stat().st_size,
            role="primary" if path.name in _TEXT_NAMES else None,
        ))
    return tuple(result)


def _primary_output(attempt_dir: Path) -> str:
    root = attempt_dir / "skill_workspace"
    for name in _TEXT_NAMES:
        candidates = sorted(root.rglob(name)) if root.is_dir() else []
        if candidates:
            return candidates[0].read_text(encoding="utf-8", errors="replace")
    return ""


def _attempt_dir(data_path: Path, attempt_id: str) -> Path:
    return data_path / "attempts" / attempt_id


class AgentOctagonAdapter:
    """Load AgentOctagon attempts into :class:`EvalSample` objects."""

    name = "agent-octagon"

    def __init__(
        self,
        data_path: str | Path,
        *,
        attempt_ids: Iterable[str] | None = None,
        run_id: str | None = None,
        include_failed: bool = True,
    ) -> None:
        self.data_path = Path(data_path)
        self.db_path = self.data_path / "octagon.db"
        self.attempt_ids = set(attempt_ids) if attempt_ids is not None else None
        self.run_id = run_id
        self.include_failed = include_failed

    def _rows(self) -> list[dict[str, Any]]:
        if not self.db_path.is_file():
            raise FileNotFoundError(f"AgentOctagon database not found: {self.db_path}")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = """
                SELECT a.*, t.prompt, t.context_json, t.constraints_json,
                       t.env_name AS task_env_name
                FROM attempts a JOIN tasks t ON t.id = a.task_id
            """
            args: list[Any] = []
            clauses: list[str] = []
            if self.run_id:
                clauses.append("a.run_id = ?")
                args.append(self.run_id)
            if self.attempt_ids:
                marks = ",".join("?" for _ in self.attempt_ids)
                clauses.append(f"a.id IN ({marks})")
                args.extend(sorted(self.attempt_ids))
            if not self.include_failed:
                clauses.append("a.status = 'completed'")
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY a.created_at, a.id"
            return [dict(row) for row in conn.execute(query, args).fetchall()]

    def _scores(self, attempt_id: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(
                "SELECT dimension, value, detail, scored_at, evaluation_manifest_ref "
                "FROM scores WHERE attempt_id=? ORDER BY id", (attempt_id,)
            ).fetchall()]

    def iter_samples(self) -> list[EvalSample]:
        samples: list[EvalSample] = []
        for row in self._rows():
            attempt_id = str(row["id"])
            attempt_dir = _attempt_dir(self.data_path, attempt_id)
            # AgentOctagon exposes two distinct layers: trajectory.json is
            # the logical step sequence and wire.jsonl is the normalized wire
            # summary. Keep raw trace/events for environment compatibility,
            # but expose the semantic layers explicitly to evaluators.
            trace = _jsonl(attempt_dir / "trace.jsonl")
            events = _jsonl(attempt_dir / "events.jsonl")
            trajectory = _read_json(attempt_dir / "trajectory.json")
            wire = _jsonl(attempt_dir / "wire.jsonl")
            thinking = _jsonl(attempt_dir / "thinking.jsonl")
            score_rows = self._scores(attempt_id)
            runtime_result = {
                "status": row.get("status"),
                "execution_status": row.get("execution_status"),
                "scoring_status": row.get("scoring_status"),
                "score_total": row.get("score_total"),
                "error_code": row.get("error_code"),
                "error_message": row.get("error_message"),
                "scores": score_rows,
            }
            context = {
                "task": {
                    "id": row.get("task_id"),
                    "env_name": row.get("env_name") or row.get("task_env_name"),
                    "prompt": row.get("prompt") or row.get("task_id"),
                    "context": _safe_json(row.get("context_json")),
                    "constraints": _safe_json(row.get("constraints_json")),
                },
                "attempt_dir": str(attempt_dir),
                "trace": trace,
                "events": events,
                "raw_trace": trace,
                "raw_events": events,
                "trajectory": trajectory,
                "wire": wire,
                "thinking": thinking,
                "final_state": _read_json(attempt_dir / "final_state.json"),
                "workspace_root": str(attempt_dir / "skill_workspace"),
                "score_rows": score_rows,
            }
            samples.append(EvalSample(
                # attempt ID is the execution-unique sample identity. task_id
                # remains stable for paired comparisons across agents.
                sample_id=attempt_id,
                task_id=str(row["task_id"]),
                task=str(row.get("prompt") or row["task_id"]),
                output=_primary_output(attempt_dir),
                expected={
                    "status": row.get("status"),
                    "score_total": row.get("score_total"),
                    "env_name": row.get("env_name") or row.get("task_env_name"),
                },
                metadata={
                    "task_id": row["task_id"],
                    "env_name": row.get("env_name") or row.get("task_env_name"),
                    "created_at": row.get("created_at"),
                },
                context=context,
                agent=AgentIdentity(
                    name=str(row.get("agent_name") or "unknown"),
                    model=row.get("model"),
                ),
                backend=self.name,
                run_id=row.get("run_id"),
                attempt_id=attempt_id,
                status=str(row.get("status") or "unknown"),
                artifacts=_artifacts(attempt_dir),
                conversation=_conversation(attempt_dir),
                runtime_result=runtime_result,
                environment={"name": row.get("env_name") or row.get("task_env_name")},
            ))
        return samples
