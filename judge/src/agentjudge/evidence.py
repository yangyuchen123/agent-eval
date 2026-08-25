"""Evidence provider boundary; no runtime-specific imports."""
from __future__ import annotations

import re
from typing import Any, Protocol
from .models import EvidenceQuery, EvidenceRecord


class EvidenceProvider(Protocol):
    def search(self, query: EvidenceQuery) -> list[EvidenceRecord]: ...
    def get(self, evidence_id: str) -> EvidenceRecord | None: ...
    def call_context(self, tool_call_id: str) -> list[EvidenceRecord]: ...
    def related(self, evidence_id: str, relation: str) -> list[EvidenceRecord]: ...


class InMemoryEvidenceProvider:
    """Small generic provider used by unit tests and local fixtures."""

    def __init__(self, records: list[EvidenceRecord]):
        self.records = records
        self._query_log: list[dict[str, Any]] = []

    def _log(self, operation: str, **payload: Any) -> None:
        self._query_log.append({"operation": operation, **payload, "result_count": payload.pop("result_count", None)})

    def search(self, query: EvidenceQuery) -> list[EvidenceRecord]:
        result = _filter_records(self.records, query)
        result = _rank_records(result, query.text)
        result = result[: query.limit]
        self._query_log.append({"operation": "search", "query": query.model_dump(), "result_ids": [r.evidence_id for r in result]})
        return result

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        result = next((record for record in self.records if record.evidence_id == evidence_id), None)
        self._query_log.append({"operation": "get", "evidence_id": evidence_id, "result_ids": [evidence_id] if result else []})
        return result

    def call_context(self, tool_call_id: str) -> list[EvidenceRecord]:
        result = [record for record in self.records if record.tool_call_id == tool_call_id]
        self._query_log.append({"operation": "call_context", "tool_call_id": tool_call_id, "result_ids": [r.evidence_id for r in result]})
        return result

    def related(self, evidence_id: str, relation: str) -> list[EvidenceRecord]:
        result = [record for record in self.records if evidence_id in record.related_evidence]
        self._query_log.append({"operation": "related", "evidence_id": evidence_id, "relation": relation, "result_ids": [r.evidence_id for r in result]})
        return result

    def query_trajectory(self) -> list[dict[str, Any]]:
        return list(self._query_log)


def _filter_records(records: list[EvidenceRecord], query: EvidenceQuery) -> list[EvidenceRecord]:
    event_types = set(query.event_type or query.kind)
    result: list[EvidenceRecord] = []
    for record in records:
        if query.source and record.source != query.source:
            continue
        if event_types and (record.event_type or record.kind) not in event_types:
            continue
        if query.tool_name and record.tool_name != query.tool_name:
            continue
        if query.agent_id and query.agent_id not in {record.agent_id, record.actor_agent_id, record.target_agent_id}:
            continue
        if query.parent_agent_id and record.parent_agent_id != query.parent_agent_id:
            continue
        if query.target_agent_id and record.target_agent_id != query.target_agent_id:
            continue
        if query.tool_call_id and record.tool_call_id != query.tool_call_id:
            continue
        if query.message_id and record.message_id != query.message_id:
            continue
        if query.after and (not record.timestamp or record.timestamp < query.after):
            continue
        if query.before and (not record.timestamp or record.timestamp > query.before):
            continue
        if query.text and not _text_matches(query.text, record):
            continue
        result.append(record)
    return result


def _rank_records(records: list[EvidenceRecord], text: str | None) -> list[EvidenceRecord]:
    if not text:
        return records
    tokens = _query_terms(text)
    if not tokens:
        return records
    scored = []
    for position, record in enumerate(records):
        haystack = _record_text(record).lower()
        score = sum(haystack.count(token) for token in tokens)
        scored.append((-score, position, record))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in scored]


def _text_matches(text: str, record: EvidenceRecord) -> bool:
    """Match natural-language queries lexically without rubric semantics.

    English words, identifiers and CJK characters are tokenized separately so
    a Judge can search a runtime using natural language without knowing the
    source runtime's JSON schema. Ranking still prefers records containing
    more query terms.
    """
    terms = _query_terms(text)
    if not terms:
        return True
    haystack = _record_text(record).lower()
    # A natural-language query may contain explanatory words that do not occur
    # verbatim in a trace. Requiring one token keeps search useful while the
    # structured filters provide precision when the Judge has it.
    return any(term in haystack for term in terms)


def _query_terms(text: str) -> list[str]:
    raw = re.findall(r"[a-z0-9_:.\-]+|[\u4e00-\u9fff]", text.lower())
    stop = {"the", "and", "what", "which", "this", "that", "agent", "的", "了", "是", "什么", "如何", "哪个"}
    return [term for term in raw if term not in stop and len(term) > 0]


def _record_text(record: EvidenceRecord) -> str:
    return " ".join([
        record.event_type or "", record.kind or "", record.tool_name or "",
        record.agent_id or "", record.actor_agent_id or "", record.target_agent_id or "",
        record.parent_agent_id or "", record.tool_call_id or "", record.message_id or "",
        record.file_path or "", str(record.content),
    ])
