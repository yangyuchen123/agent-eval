"""Human-maintained gold judgments for AgentEval meta-evaluation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import json


@dataclass(frozen=True)
class GoldJudgment:
    case_id: str
    question_id: str
    expected_score: float | None
    expected_status: str
    applicability: str | None = None
    expected_stratum: str | None = None
    positive_evidence_refs: list[str] = field(default_factory=list)
    negative_evidence_refs: list[str] = field(default_factory=list)
    required_evidence_refs: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.expected_score is not None and not 0 <= self.expected_score <= 1:
            raise ValueError("expected_score must be in [0, 1] or None")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GoldJudgment":
        return cls(
            case_id=str(value["case_id"]), question_id=str(value["question_id"]),
            expected_score=value.get("expected_score"),
            expected_status=str(value["expected_status"]),
            applicability=value.get("applicability"),
            expected_stratum=value.get("expected_stratum"),
            positive_evidence_refs=[str(x) for x in value.get("positive_evidence_refs", [])],
            negative_evidence_refs=[str(x) for x in value.get("negative_evidence_refs", [])],
            required_evidence_refs=[str(x) for x in value.get("required_evidence_refs", [])],
            missing_evidence=[str(x) for x in value.get("missing_evidence", [])],
            notes=value.get("notes"),
        )


def load_gold(path: str | Path) -> GoldJudgment:
    return GoldJudgment.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def load_gold_dir(path: str | Path) -> list[GoldJudgment]:
    root = Path(path)
    return [load_gold(item) for item in sorted(root.glob("*.json")) if item.name != "README.json"]


def write_gold(path: str | Path, judgment: GoldJudgment) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(judgment.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
