"""Read-only discovery adapter for AgentOctagon attempts and environments.

This module deliberately does not run AgentOctagon or import its evaluator. It
only joins archived attempt files with the local Octagon metadata database so
MetaEval can select real, reproducible cases without moving runtime ownership
into AgentEval.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
import json
import sqlite3
import shutil
import tempfile
from typing import Any, Iterable


@dataclass(frozen=True)
class OctagonAttempt:
    attempt_id: str
    run_id: str | None
    task_id: str | None
    env_name: str | None
    status: str | None
    score_total: float | None
    model: str | None
    started_at: str | None
    ended_at: str | None
    attempt_dir: str
    trace_path: str | None
    wire_path: str | None
    trajectory_path: str | None
    artifact_paths: tuple[str, ...] = ()
    score_dimensions: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_trace(self) -> bool:
        return self.trace_path is not None

    @property
    def trace_digest(self) -> str | None:
        return _digest(self.trace_path)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["has_trace"] = self.has_trace
        result["trace_digest"] = self.trace_digest
        return result


class OctagonDiscovery:
    """Discover archived attempts, scores and environment metadata read-only."""

    def __init__(self, root: str | Path = "/home/yang/agent-octagon"):
        self.root = Path(root)
        self.attempts_root = self.root / "data" / "attempts"
        self.envs_root = self.root / "envs"
        self.db_path = self.root / "data" / "octagon.db"
        self._db_read_path: Path | None = None

    def discover(self, *, env_name: str | None = None, task_id: str | None = None,
                 only_with_trace: bool = True, limit: int | None = None) -> list[OctagonAttempt]:
        rows = self._attempt_rows(env_name=env_name, task_id=task_id, limit=limit)
        results = []
        for row in rows:
            attempt_dir = self.attempts_root / row["id"]
            if not attempt_dir.is_dir():
                continue
            files = {path.name: path for path in attempt_dir.iterdir() if path.is_file()}
            trace = files.get("trace.jsonl")
            if only_with_trace and trace is None:
                continue
            dimensions = self._score_dimensions(row["id"])
            artifacts = tuple(str(path) for path in sorted(attempt_dir.iterdir()) if path.is_file() and path.name not in {"trace.jsonl", "wire.jsonl", "trajectory.json"})
            results.append(OctagonAttempt(
                attempt_id=row["id"], run_id=row["run_id"], task_id=row["task_id"], env_name=row["env_name"],
                status=row["status"], score_total=row["score_total"], model=row["model"],
                started_at=row["started_at"], ended_at=row["ended_at"], attempt_dir=str(attempt_dir),
                trace_path=str(trace) if trace else None,
                wire_path=str(files["wire.jsonl"]) if "wire.jsonl" in files else None,
                trajectory_path=str(files["trajectory.json"]) if "trajectory.json" in files else None,
                artifact_paths=artifacts, score_dimensions=dimensions,
                metadata={"env_path": str(self.envs_root / row["env_name"]) if row["env_name"] else None},
            ))
        return results

    def task_prompt(self, task_id: str | None) -> str | None:
        if not task_id:
            return None
        connection = sqlite3.connect(f"file:{self._database_for_read()}?mode=ro", uri=True)
        try:
            row = connection.execute("SELECT prompt FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return str(row[0]) if row and row[0] is not None else None
        finally:
            connection.close()

    def task_groups(self, attempts: Iterable[OctagonAttempt]) -> dict[str, list[OctagonAttempt]]:
        groups: dict[str, list[OctagonAttempt]] = {}
        for attempt in attempts:
            key = f"{attempt.env_name or 'unknown'}::{attempt.task_id or attempt.attempt_id}"
            groups.setdefault(key, []).append(attempt)
        return groups

    def environment_inventory(self) -> list[dict[str, Any]]:
        if not self.envs_root.is_dir():
            return []
        result = []
        for path in sorted(self.envs_root.iterdir()):
            if not path.is_dir():
                continue
            result.append({
                "env_name": path.name,
                "path": str(path),
                "has_scorer": (path / "scorer.py").is_file(),
                "has_readme": any((path / name).is_file() for name in ("README.md", "README.zh.md")),
                "task_files": [str(item) for item in sorted(path.glob("tasks/*")) if item.is_file()],
            })
        return result

    def _database_for_read(self) -> Path:
        if self._db_read_path is None:
            # Work from a snapshot: AgentOctagon may still be writing its DB,
            # and a snapshot is also the correct replay boundary for MetaEval.
            fd, name = tempfile.mkstemp(prefix="agenteval-octagon-", suffix=".db")
            import os
            os.close(fd)
            shutil.copyfile(self.db_path, name)
            self._db_read_path = Path(name)
        return self._db_read_path

    def _attempt_rows(self, *, env_name: str | None, task_id: str | None, limit: int | None) -> list[sqlite3.Row]:
        if not self.db_path.is_file():
            return []
        connection = sqlite3.connect(f"file:{self._database_for_read()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        clauses, params = [], []
        if env_name:
            clauses.append("env_name = ?"); params.append(env_name)
        if task_id:
            clauses.append("task_id = ?"); params.append(task_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        suffix = f" LIMIT {int(limit)}" if limit is not None else ""
        try:
            return connection.execute(f"SELECT id, run_id, task_id, env_name, status, score_total, model, started_at, ended_at FROM attempts{where} ORDER BY created_at DESC{suffix}", params).fetchall()
        finally:
            connection.close()

    def _score_dimensions(self, attempt_id: str) -> dict[str, float]:
        connection = sqlite3.connect(f"file:{self._database_for_read()}?mode=ro", uri=True)
        try:
            return {str(row[0]): float(row[1]) for row in connection.execute("SELECT dimension, value FROM scores WHERE attempt_id = ?", (attempt_id,))}
        finally:
            connection.close()


def write_inventory(path: str | Path, attempts: Iterable[OctagonAttempt], environments: Iterable[dict[str, Any]] = ()) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": "agenteval.octagon_inventory.v1", "attempts": [item.to_dict() for item in attempts], "environments": list(environments)}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _digest(path: str | None) -> str | None:
    if not path or not Path(path).is_file():
        return None
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
