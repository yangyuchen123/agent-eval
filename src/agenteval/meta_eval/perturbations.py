"""Deterministic evidence and rubric perturbations for replay experiments."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import random
from typing import Any, Mapping


@dataclass(frozen=True)
class EvidenceSnapshot:
    records: tuple[Mapping[str, Any], ...]
    snapshot_digest: str

    @classmethod
    def from_records(cls, records: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...]) -> "EvidenceSnapshot":
        data = tuple(dict(r) for r in records)
        digest = sha256(_canonical(data).encode()).hexdigest()
        return cls(data, digest)

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_digest": self.snapshot_digest, "record_count": len(self.records), "records": list(self.records)}


def record_id(record: Mapping[str, Any]) -> str:
    return str(record.get("evidence_id") or record.get("id") or record.get("ref") or "")


def reorder(snapshot: EvidenceSnapshot, seed: int) -> EvidenceSnapshot:
    records = list(snapshot.records)
    random.Random(seed).shuffle(records)
    return EvidenceSnapshot.from_records(records)


def add_distractors(snapshot: EvidenceSnapshot, distractors: list[Mapping[str, Any]]) -> EvidenceSnapshot:
    return EvidenceSnapshot.from_records(list(snapshot.records) + [dict(x) for x in distractors])


def lengthen(snapshot: EvidenceSnapshot, factor: int, *, seed: int = 0) -> EvidenceSnapshot:
    """Increase catalog size with unique, semantically irrelevant no-op events.

    Real runtime records are never duplicated. Injected records have unique
    ids, an explicit synthetic source and no runtime relations. This tests
    length sensitivity; keyword distractor robustness is a separate test.
    """
    if factor < 1:
        raise ValueError("factor must be >= 1")
    original = list(snapshot.records)
    target_extra = len(original) * (factor - 1)
    noise = [
        {
            "evidence_id": f"meta_eval.synthetic:{seed}:{index}",
            "source": "meta_eval.synthetic",
            "line": index + 1,
            "event_type": "meta_eval:irrelevant_noop",
            "kind": "meta_eval:irrelevant_noop",
            "evidence_class": "derived_runtime_relation",
            "claim_strength": "indirect",
            "actor_agent_id": None,
            "target_agent_id": None,
            "agent_id": None,
            "parent_agent_id": None,
            "tool_name": None,
            "tool_call_id": None,
            "message_id": None,
            "timestamp": None,
            "file_path": None,
            "lifecycle_state": "noop",
            "content": {"meta_eval_noise": True, "seed": seed, "index": index,
                        "description": "synthetic unrelated observability heartbeat"},
            "related_evidence": [],
        }
        for index in range(target_extra)
    ]
    return EvidenceSnapshot.from_records(original + noise)

def remove(snapshot: EvidenceSnapshot, evidence_ids: set[str]) -> EvidenceSnapshot:
    return EvidenceSnapshot.from_records([r for r in snapshot.records if record_id(r) not in evidence_ids])


def paraphrase_question(question: Mapping[str, Any], text: str) -> dict[str, Any]:
    result = dict(question)
    result["question"] = text
    return result


def _canonical(value: Any) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
