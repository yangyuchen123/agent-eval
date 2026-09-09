"""AgentEval schema adapter; RRD core remains taxonomy agnostic."""
from __future__ import annotations
from typing import Any, Mapping, Sequence
from .models import Rubric


def to_rrd_rubrics(criteria: Sequence[Mapping[str, Any]]) -> list[Rubric]:
    return [Rubric.from_mapping(x, i) for i, x in enumerate(criteria)]


def from_rrd_rubrics(rubrics: Sequence[Rubric], originals: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Restore AgentEval fields and preserve parent provenance for children."""
    output = []
    for rubric in rubrics:
        source_id = rubric.rubric_id
        parent_id = source_id.split(".", 1)[0]
        source = dict(originals.get(source_id) or originals.get(parent_id) or {})
        source["criterion_id"] = rubric.rubric_id
        source["criterion"] = rubric.text
        source["source_criterion_id"] = parent_id if parent_id != source_id else source.get("source_criterion_id")
        source.pop("rubric_id", None)
        source.pop("text", None)
        output.append(source)
    return output
