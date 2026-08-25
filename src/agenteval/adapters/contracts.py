"""Runtime-neutral evaluation contracts.

Harbor and AgentOctagon are execution backends, not scoring formats.  This
module defines the smallest common representation that a scoring package can
consume without importing either runtime's storage/database code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from ..protocols import Case


@dataclass(frozen=True)
class AgentIdentity:
    name: str
    model: str | None = None
    version: str | None = None
    provider: str | None = None
    config_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model": self.model,
            "version": self.version,
            "provider": self.provider,
            "config_hash": self.config_hash,
        }


@dataclass(frozen=True)
class ArtifactRef:
    """A portable artifact reference; paths should be bundle-relative."""

    path: str
    type: str = "file"
    status: str = "ok"
    media_type: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    role: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "type": self.type,
            "status": self.status,
            "media_type": self.media_type,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "role": self.role,
        }


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: Any = None
    result: Any = None
    turn_id: str | None = None
    status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "arguments": self.arguments,
            "result": self.result,
            "turn_id": self.turn_id,
            "status": self.status,
        }


@dataclass(frozen=True)
class ConversationTurn:
    turn_id: str
    role: str
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "role": self.role,
            "content": self.content,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class EvalSample:
    """Normalized output of a runtime adapter.

    ``Case`` remains the scorer-facing task/gold object.  ``EvalSample`` adds
    execution provenance and rich runtime data needed by multi-turn scorers.
    ``context`` is evaluator-only and may contain references to private,
    bundle-relative resources; it is never sent to the agent.
    """

    sample_id: str
    task_id: str
    task: str
    output: str = ""
    expected: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    agent: AgentIdentity = field(default_factory=lambda: AgentIdentity("unknown"))
    backend: str = "unknown"
    run_id: str | None = None
    attempt_id: str | None = None
    status: str = "finished"
    artifacts: tuple[ArtifactRef, ...] = ()
    conversation: tuple[ConversationTurn, ...] = ()
    runtime_result: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)

    def to_case(self) -> Case:
        """Project the rich sample into the existing scorer Case contract."""
        context = dict(self.context)
        context.update({
            # Keep a lossless reconstruction payload for adapter-owned skills
            # (notably the Octagon scorer bridge).
            "_eval_sample": self.to_dict(),
            "sample_id": self.sample_id,
            "task_id": self.task_id,
            "agent": self.agent.to_dict(),
            "backend": self.backend,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "status": self.status,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "conversation": [turn.to_dict() for turn in self.conversation],
            "runtime_result": self.runtime_result,
            "environment": self.environment,
        })
        return Case(
            case_id=self.sample_id,
            task=self.task,
            expected=dict(self.expected),
            context=context,
            metadata={**self.metadata, "task_id": self.task_id},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "agenteval.eval_sample.v1",
            "sample_id": self.sample_id,
            "task_id": self.task_id,
            "task": self.task,
            "output": self.output,
            "expected": self.expected,
            "metadata": self.metadata,
            "context": self.context,
            "agent": self.agent.to_dict(),
            "backend": self.backend,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "status": self.status,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "conversation": [turn.to_dict() for turn in self.conversation],
            "runtime_result": self.runtime_result,
            "environment": self.environment,
        }


class RuntimeAdapter(Protocol):
    """Adapter from a runtime's persisted runs to normalized EvalSamples."""

    name: str

    def iter_samples(self) -> Sequence[EvalSample]:
        ...
