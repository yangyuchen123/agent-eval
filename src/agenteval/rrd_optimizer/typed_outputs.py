"""PydanticAI output contracts for RRD calls."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class MatrixOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    matrix: dict[str, dict[str, Literal[0, 1]]]

class DecompositionChildOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rubric_id: str
    text: str = Field(min_length=1)

class DecompositionItemOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_rubric_id: str
    action: Literal["KEEP", "SPLIT"]
    reason: str = ""
    children: list[DecompositionChildOutput] = Field(default_factory=list)

class DecompositionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposals: list[DecompositionItemOutput]

class InitialRubricOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rubric_id: str
    text: str = Field(min_length=1)

class InitialOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rubrics: list[InitialRubricOutput]


class ClassificationCapabilityOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary: str
    secondary: list[str] = Field(default_factory=list)


class ClassificationItemOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion_id: str
    grounding: Literal["human_general", "benchmark_specific", "task_specific"]
    grounding_secondary: list[str] = Field(default_factory=list)
    scope: Literal["process", "outcome", "policy", "artifact"]
    scope_secondary: list[str] = Field(default_factory=list)
    applicability: Literal["always", "conditional", "task_specific"]
    evidence_source: Literal["trajectory", "artifact", "state", "mixed"]
    atomicity: Literal["atomic", "compound"]
    subrequirements: list[str] = Field(default_factory=list)
    aggregation_rule: str = "not_applicable"
    hardness: Literal["hard", "soft"]
    judgment_type: Literal["objective", "subjective"]
    capability: ClassificationCapabilityOutput
    confidence: Literal["high", "medium", "low"] = "medium"
    basis: str = ""


class ClassificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[ClassificationItemOutput]
