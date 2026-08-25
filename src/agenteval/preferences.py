"""Human preference examples and versioned meta-rubrics.

Preference examples are supervision data, not judge prompts.  They capture
what a human preferred and why; a rubric planner can later abstract them into
cross-case principles and instantiate a case-specific :class:`Rubric`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

PREFERENCE_SCHEMA = "agenteval.preference_example.v1"
META_RUBRIC_SCHEMA = "agenteval.meta_rubric.v1"


@dataclass(frozen=True)
class PreferenceExample:
    example_id: str
    case: dict[str, Any]
    candidates: tuple[dict[str, Any], ...]
    preferred: str
    rejected: str | None = None
    human_reason: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ids = [str(c.get("id") or "") for c in self.candidates]
        if not self.example_id or len(self.candidates) < 2:
            raise ValueError("preference example requires id and at least two candidates")
        if not self.preferred or self.preferred not in ids:
            raise ValueError(f"preferred candidate {self.preferred!r} is not present")
        if self.rejected is not None and self.rejected not in ids:
            raise ValueError(f"rejected candidate {self.rejected!r} is not present")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PREFERENCE_SCHEMA,
            "example_id": self.example_id,
            "case": self.case,
            "candidates": list(self.candidates),
            "preference": {"preferred": self.preferred, "rejected": self.rejected},
            "human_reason": list(self.human_reason),
            "dimensions": list(self.dimensions),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PreferenceExample":
        pref = data.get("preference") or {}
        return cls(
            example_id=str(data.get("example_id") or ""),
            case=dict(data.get("case") or {}),
            candidates=tuple(dict(x) for x in (data.get("candidates") or [])),
            preferred=str(pref.get("preferred") or data.get("preferred") or ""),
            rejected=(str(pref["rejected"]) if pref.get("rejected") is not None else None),
            human_reason=tuple(str(x) for x in (data.get("human_reason") or data.get("reason") or [])),
            dimensions=tuple(str(x) for x in (data.get("dimensions") or [])),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class MetaPrinciple:
    principle_id: str
    name: str
    description: str
    positive_anchors: tuple[str, ...] = ()
    negative_anchors: tuple[str, ...] = ()
    source_examples: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.principle_id,
            "name": self.name,
            "description": self.description,
            "positive_anchors": list(self.positive_anchors),
            "negative_anchors": list(self.negative_anchors),
            "source_examples": list(self.source_examples),
            "capabilities": list(self.capabilities),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MetaPrinciple":
        pid = str(data.get("id") or data.get("principle_id") or "")
        if not pid or not str(data.get("description") or ""):
            raise ValueError("meta principle requires id and description")
        return cls(
            principle_id=pid,
            name=str(data.get("name") or pid),
            description=str(data["description"]),
            positive_anchors=tuple(str(x) for x in (data.get("positive_anchors") or [])),
            negative_anchors=tuple(str(x) for x in (data.get("negative_anchors") or [])),
            source_examples=tuple(str(x) for x in (data.get("source_examples") or [])),
            capabilities=tuple(str(x) for x in (data.get("capabilities") or [])),
        )


@dataclass(frozen=True)
class MetaRubric:
    rubric_id: str
    version: str
    description: str
    principles: tuple[MetaPrinciple, ...]
    source_examples: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": META_RUBRIC_SCHEMA,
            "rubric_id": self.rubric_id,
            "version": self.version,
            "description": self.description,
            "principles": [p.to_dict() for p in self.principles],
            "source_examples": list(self.source_examples),
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MetaRubric":
        rid = str(data.get("rubric_id") or "")
        version = str(data.get("version") or "")
        principles = tuple(MetaPrinciple.from_dict(x) for x in (data.get("principles") or []))
        if not rid or not version or not principles:
            raise ValueError("meta rubric requires rubric_id, version and principles")
        return cls(rid, version, str(data.get("description") or ""), principles,
                   tuple(str(x) for x in (data.get("source_examples") or [])),
                   dict(data.get("provenance") or {}))


class PreferenceStore:
    """Read preference examples from a JSON array, JSONL file, or directory."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> list[PreferenceExample]:
        paths = sorted(self.path.glob("*.json")) + sorted(self.path.glob("*.jsonl")) if self.path.is_dir() else [self.path]
        result: list[PreferenceExample] = []
        for path in paths:
            if path.suffix == ".jsonl":
                values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            else:
                value = json.loads(path.read_text(encoding="utf-8"))
                values = value.get("examples", []) if isinstance(value, dict) else value
            if not isinstance(values, list):
                raise ValueError(f"preference file must contain an array: {path}")
            result.extend(PreferenceExample.from_dict(dict(item)) for item in values)
        ids = [x.example_id for x in result]
        if len(ids) != len(set(ids)):
            raise ValueError("preference examples contain duplicate example_id")
        if not result:
            raise ValueError(f"no preference examples found at {self.path}")
        return result

    @staticmethod
    def save_meta(path: str | Path, rubric: MetaRubric) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(rubric.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target

    @staticmethod
    def load_meta(path: str | Path) -> MetaRubric:
        return MetaRubric.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
