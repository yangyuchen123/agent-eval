"""File-backed adapter for normalized EvalSample JSON.

This is useful as a stable handoff format while Harbor and AgentOctagon
adapters are developed independently.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import (
    AgentIdentity,
    ArtifactRef,
    ConversationTurn,
    EvalSample,
    ToolCall,
)


def _tool_call(data: dict[str, Any]) -> ToolCall:
    return ToolCall(
        call_id=str(data.get("call_id") or ""),
        name=str(data.get("name") or ""),
        arguments=data.get("arguments"),
        result=data.get("result"),
        turn_id=data.get("turn_id"),
        status=str(data.get("status") or "ok"),
    )


def _turn(data: dict[str, Any]) -> ConversationTurn:
    return ConversationTurn(
        turn_id=str(data.get("turn_id") or ""),
        role=str(data.get("role") or "unknown"),
        content=data.get("content"),
        tool_calls=tuple(_tool_call(item) for item in data.get("tool_calls", [])),
        timestamp=data.get("timestamp"),
    )


def sample_from_dict(data: dict[str, Any]) -> EvalSample:
    agent_data = data.get("agent") or {}
    return EvalSample(
        sample_id=str(data.get("sample_id") or data.get("case_id") or ""),
        task_id=str(data.get("task_id") or data.get("case_id") or ""),
        task=str(data.get("task") or ""),
        output=str(data.get("output") or ""),
        expected=dict(data.get("expected") or {}),
        metadata=dict(data.get("metadata") or {}),
        context=dict(data.get("context") or {}),
        agent=AgentIdentity(
            name=str(agent_data.get("name") or "unknown"),
            model=agent_data.get("model"),
            version=agent_data.get("version"),
            provider=agent_data.get("provider"),
            config_hash=agent_data.get("config_hash"),
        ),
        backend=str(data.get("backend") or "unknown"),
        run_id=data.get("run_id"),
        attempt_id=data.get("attempt_id"),
        status=str(data.get("status") or "finished"),
        artifacts=tuple(ArtifactRef(**item) for item in data.get("artifacts", [])),
        conversation=tuple(_turn(item) for item in data.get("conversation", [])),
        runtime_result=dict(data.get("runtime_result") or {}),
        environment=dict(data.get("environment") or {}),
    )


class JsonRuntimeAdapter:
    name = "json"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def iter_samples(self) -> list[EvalSample]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        raw = payload.get("samples") if isinstance(payload, dict) else payload
        if not isinstance(raw, list):
            raise ValueError(f"normalized sample file must contain a samples array: {self.path}")
        samples = [sample_from_dict(item) for item in raw]
        ids = [sample.sample_id for sample in samples]
        if any(not sample_id for sample_id in ids):
            raise ValueError("normalized samples require non-empty sample_id")
        if len(ids) != len(set(ids)):
            raise ValueError("normalized samples contain duplicate sample_id")
        return samples
