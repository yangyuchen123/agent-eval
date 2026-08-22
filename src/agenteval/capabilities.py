"""Capability taxonomy: the cross-benchmark semantic axis as structured data.

A capability is a latent skill that evaluation questions measure. Keeping
them in a small ontology (id + description + parent) instead of free-form
tags makes future automation tractable:

    software_engineering
    ├── code_reasoning
    ├── code_quality
    └── testing
    document_production
    ├── format_compliance
    └── numerical_accuracy

Nothing here is automatic yet (per the roadmap gate: no auto-generation
until ≥50 cases / ≥3 agents / ≥2 rubric versions). This is the *schema*
so that 50 benchmarks × 500 questions remain maintainable by hand.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

TAXONOMY_SCHEMA = "agenteval.capability_taxonomy.v1"


@dataclass(frozen=True)
class Capability:
    id: str
    description: str
    parent: str | None = None      # parent capability id; None = root

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "description": self.description,
                "parent": self.parent}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Capability":
        cid = str(data.get("id") or "")
        if not cid:
            raise ValueError("capability requires an id")
        parent = data.get("parent")
        return cls(id=cid,
                   description=str(data.get("description") or ""),
                   parent=str(parent) if parent else None)


class CapabilityStore:
    """Load/validate a capability taxonomy (one JSON file)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict[str, Capability]:
        if not self.path.is_file():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        items = data.get("capabilities", data) if isinstance(data, dict) else data
        caps = {c.id: c for c in (Capability.from_dict(x) for x in items)}
        self._validate(caps)
        return caps

    @staticmethod
    def _validate(caps: dict[str, Capability]) -> None:
        for cap in caps.values():
            if cap.parent is not None and cap.parent not in caps:
                raise ValueError(
                    f"capability {cap.id!r} references unknown parent "
                    f"{cap.parent!r}")

    def children(self, caps: Mapping[str, Capability],
                 parent_id: str) -> list[str]:
        return sorted(c.id for c in caps.values() if c.parent == parent_id)

    def roots(self, caps: Mapping[str, Capability]) -> list[str]:
        return sorted(c.id for c in caps.values() if c.parent is None)

    def tree(self, caps: Mapping[str, Capability]) -> dict[str, Any]:
        """Nested {capability_id: {children: {...}}} structure for reports."""

        def node(cid: str) -> dict[str, Any]:
            kids = self.children(caps, cid)
            return {"description": caps[cid].description,
                    "children": {k: node(k) for k in kids}}

        return {r: node(r) for r in self.roots(caps)}

    def validate_question_tags(
        self, caps: Mapping[str, Capability],
        question_capabilities: Mapping[str, Mapping[str, Iterable[str]]],
    ) -> list[str]:
        """Check that question capability tags exist in the taxonomy."""
        unknown = []
        for skill, mapping in question_capabilities.items():
            for qid, tags in mapping.items():
                for tag in tags:
                    if tag not in caps:
                        unknown.append(f"{skill}.{qid}:{tag}")
        return unknown


DEFAULT_TAXONOMY: dict[str, Any] = {
    "schema_version": TAXONOMY_SCHEMA,
    "capabilities": [
        {"id": "software_engineering", "parent": None,
         "description": "Ability to understand, modify and produce correct software"},
        {"id": "code_reasoning", "parent": "software_engineering",
         "description": "Understand code intent and reason about behavior"},
        {"id": "root_cause_analysis", "parent": "code_reasoning",
         "description": "Locate the actual cause of a defect, not a symptom"},
        {"id": "edge_case_handling", "parent": "code_reasoning",
         "description": "Handle boundary and exceptional inputs"},
        {"id": "regression_risk_assessment", "parent": "code_reasoning",
         "description": "Judge whether a change breaks unrelated paths"},
        {"id": "code_quality", "parent": "software_engineering",
         "description": "Produce readable, idiomatic, maintainable code"},
        {"id": "change_localization", "parent": "code_quality",
         "description": "Keep changes minimal and confined to relevant areas"},
        {"id": "code_efficiency", "parent": "code_quality",
         "description": "Produce minimal, non-redundant changes"},
        {"id": "readability", "parent": "code_quality",
         "description": "Clear naming, obvious intent, easy to follow"},
        {"id": "style_consistency", "parent": "code_quality",
         "description": "Consistent with the surrounding codebase conventions"},
        {"id": "communicative_clarity", "parent": "code_quality",
         "description": "The diff/change is self-explanatory"},
        {"id": "requirement_understanding", "parent": "software_engineering",
         "description": "Match the change to what the task/issue promised"},
        {"id": "test_alignment", "parent": "requirement_understanding",
         "description": "Change aligns with expected tests without gaming them"},
        {"id": "meta_judgeability", "parent": None,
         "description": "The output is clear enough to be judged at all"},

        {"id": "document_production", "parent": None,
         "description": "Produce professional documents, spreadsheets and reports"},
        {"id": "format_compliance", "parent": "document_production",
         "description": "Deliverables meet file/worksheet/layout requirements"},
        {"id": "numerical_accuracy", "parent": "document_production",
         "description": "Numbers, formulas and calculations are correct"},
        {"id": "data_handling", "parent": "document_production",
         "description": "Correctly read, reference and use data sources"},
        {"id": "content_accuracy", "parent": "document_production",
         "description": "Facts and content match the request"},
        {"id": "completeness", "parent": "document_production",
         "description": "All required sections/items are present"},
        {"id": "professional_quality", "parent": "document_production",
         "description": "Deliverable looks professional and well-organized"},
        {"id": "compliance_standards", "parent": "document_production",
         "description": "Meets stated standards, policies and constraints"},
        {"id": "uncategorized", "parent": None,
         "description": "No capability tag matched (fallback)"},
    ],
}
