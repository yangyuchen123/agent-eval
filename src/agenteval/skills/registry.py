"""Skill registry: where evaluation domains plug in.

Case packages register their skills here. The framework's router and
runner only talk to the registry — they never import domain code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..protocols import SkillSpec
from .base import Skill


@dataclass
class SkillRegistry:
    skills: dict[str, Skill] = field(default_factory=dict)

    def register(self, skill: Skill) -> None:
        if not skill.skill_id:
            raise ValueError("skill.skill_id must be set")
        if skill.skill_id in self.skills:
            raise ValueError(f"duplicate skill: {skill.skill_id}")
        self.skills[skill.skill_id] = skill

    def get(self, skill_id: str) -> Skill:
        try:
            return self.skills[skill_id]
        except KeyError:
            raise KeyError(f"unknown skill: {skill_id!r}; registered: {sorted(self.skills)}")

    def catalog(self) -> list[dict[str, Any]]:
        """Static skill list consumed by routers and reports."""
        return [s.spec().to_dict() for s in self.skills.values()]

    def specs(self) -> dict[str, SkillSpec]:
        return {sid: s.spec() for sid, s in self.skills.items()}

    def __len__(self) -> int:
        return len(self.skills)
