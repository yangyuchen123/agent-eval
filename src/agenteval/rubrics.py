"""Rubric as data: the first step toward rubric optimization.

A rubric is a *versioned, serializable, reviewable artifact* — not code.
This is what makes later phases possible:
    Phase 2  history   — record which rubric version produced which score
    Phase 3  analysis  — per-question variance / judge disagreement
    Phase 4  proposal  — LLM proposes rubric edits, human approves

Design:
* ``RubricQuestion`` — one fine-grained question with per-anchor scoring
  definitions and an evidence requirement (HarnessEval-style).
* ``Rubric`` — ordered questions + meta questions (no literal-evidence
  required) + discrete score ladder.
* ``RubricStore`` — load/save/validate/version rubrics as JSON files.

Nothing here touches LLM backends — rubrics are pure data.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RUBRIC_SCHEMA = "agenteval.rubric.v1"
DEFAULT_ALLOWED_SCORES = (0.0, 0.25, 0.5, 0.75, 1.0)


@dataclass(frozen=True)
class RubricQuestion:
    id: str
    question: str
    anchors: str                 # per-anchor score definitions
    evidence: str                # what the judge must quote
    weight: float = 1.0
    # concept lineage: ids of ancestor questions this question descends
    # from across rubric versions. Empty = this id is its own lineage.
    # Needed by Phase 3.3 (version migration) and the future proposer.
    lineage: tuple[str, ...] = ()
    # latent capabilities this question measures (cross-benchmark axis).
    # E.g. ("numerical_accuracy", "formula_reasoning"). Capability-level
    # reports aggregate questions across benchmarks by these tags — this
    # is the abstraction that makes cross-benchmark analysis meaningful.
    capabilities: tuple[str, ...] = ()
    # Generated-rubric provenance: which meta-principles justify this question?
    source_principles: tuple[str, ...] = ()
    case_adaptation: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "id": self.id, "question": self.question,
            "anchors": self.anchors, "evidence": self.evidence,
            "weight": self.weight,
        }
        if self.lineage:
            d["lineage"] = list(self.lineage)
        if self.capabilities:
            d["capabilities"] = list(self.capabilities)
        if self.source_principles:
            d["source_principles"] = list(self.source_principles)
        if self.case_adaptation:
            d["case_adaptation"] = self.case_adaptation
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RubricQuestion":
        qid = str(data.get("id") or "")
        if not qid or not str(data.get("question") or ""):
            raise ValueError(f"invalid rubric question: {qid!r}")
        return cls(
            id=qid,
            question=str(data["question"]),
            anchors=str(data.get("anchors") or ""),
            evidence=str(data.get("evidence") or ""),
            weight=float(data.get("weight", 1.0)),
            lineage=tuple(str(x) for x in (data.get("lineage") or ())),
            capabilities=tuple(str(x) for x in (data.get("capabilities") or ())),
            source_principles=tuple(str(x) for x in (data.get("source_principles") or ())),
            case_adaptation=str(data.get("case_adaptation") or ""),
        )


@dataclass(frozen=True)
class Rubric:
    """A versioned set of evaluation questions.

    ``meta_questions`` are questions whose 'evidence' is a summary rather
    than a verbatim quote (e.g. a judgeable-gate question), so they are
    exempt from the anti-fabrication quote check.
    """

    rubric_id: str
    version: str
    description: str
    questions: tuple[RubricQuestion, ...]
    meta_questions: frozenset[str] = frozenset()
    allowed_scores: tuple[float, ...] = DEFAULT_ALLOWED_SCORES
    score_schema: str = RUBRIC_SCHEMA
    # Provenance for generated rubrics: source meta-rubric, preference examples,
    # and case adaptation decisions. Kept optional for backward compatibility.
    provenance: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------ data ----
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.score_schema,
            "rubric_id": self.rubric_id,
            "version": self.version,
            "description": self.description,
            "questions": [q.to_dict() for q in self.questions],
            "meta_questions": sorted(self.meta_questions),
            "allowed_scores": list(self.allowed_scores),
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rubric":
        rubric_id = str(data.get("rubric_id") or "")
        version = str(data.get("version") or "")
        if not rubric_id or not version:
            raise ValueError(f"rubric requires rubric_id and version: {rubric_id!r}")
        questions = tuple(
            RubricQuestion.from_dict(q) for q in (data.get("questions") or []))
        if not questions:
            raise ValueError(f"rubric {rubric_id!r} has no questions")
        allowed = tuple(float(s) for s in (data.get("allowed_scores")
                                           or DEFAULT_ALLOWED_SCORES))
        return cls(
            rubric_id=rubric_id,
            version=version,
            description=str(data.get("description") or ""),
            questions=questions,
            meta_questions=frozenset(str(x) for x in (data.get("meta_questions") or [])),
            allowed_scores=allowed,
            provenance=dict(data.get("provenance") or {}),
        )

    # ---------------------------------------------------------- helpers ----
    @property
    def question_ids(self) -> tuple[str, ...]:
        return tuple(q.id for q in self.questions)

    def is_meta(self, question_id: str) -> bool:
        return question_id in self.meta_questions


class RubricStore:
    """Load/save/validate rubric JSON files (one file per rubric)."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def path_for(self, rubric_id: str) -> Path:
        return self.root / f"{rubric_id}.json"

    def load(self, rubric_id: str) -> Rubric:
        path = self.path_for(rubric_id)
        if not path.is_file():
            raise FileNotFoundError(f"no rubric file at {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        rubric = Rubric.from_dict(data)
        if rubric.rubric_id != rubric_id:
            raise ValueError(
                f"file {path.name} declares rubric_id {rubric.rubric_id!r}, "
                f"expected {rubric_id!r}")
        return rubric

    def save(self, rubric: Rubric) -> Path:
        path = self.path_for(rubric.rubric_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(rubric.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        return path

    def list_rubrics(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))


def normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def normalize_patch(patch: str) -> str:
    """Normalize a diff to source text so quoted evidence can match."""
    lines = []
    for line in patch.splitlines():
        stripped = line.strip()
        if stripped.startswith("diff --git"):
            m = re.search(r"diff --git a/(\S+)", stripped)
            if m:
                lines.append(m.group(1))
            continue
        if stripped.startswith(("---", "+++", "index", "@@")):
            continue
        if stripped.startswith(("+", "-")):
            stripped = stripped[1:].strip()
        if stripped:
            lines.append(stripped)
    return normalize_whitespace(" ".join(lines))


def evidence_in_patch(evidence: str, norm_patch: str) -> bool:
    """Every quoted fragment (split on '...') must appear in the patch."""
    for segment in re.split(r"\.\.\.", evidence):
        segment = normalize_whitespace(segment)
        if segment and segment not in norm_patch:
            return False
    return True
