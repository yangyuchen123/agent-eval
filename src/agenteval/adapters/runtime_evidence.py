"""Runtime-neutral, queryable evidence extracted from agent traces.

The evidence index is deliberately separate from the judge prompt.  It keeps
useful semantic content (tool arguments/results and completed messages), drops
streaming delta fragments, and exposes bounded grep-style queries for a judge.
It does not assign task-specific meaning to runtime events.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class EvidenceHit:
    evidence_id: str
    source: str
    line: int | None
    kind: str | None
    record: dict[str, Any]
    matched_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source": self.source,
            "line": self.line,
            "kind": self.kind,
            "matched_fields": list(self.matched_fields),
            "record": self.record,
        }


class RuntimeEvidenceIndex:
    """A bounded-query index over normalized and legacy runtime records."""

    def __init__(self, records: Iterable[dict[str, Any]] = ()) -> None:
        self.records: list[dict[str, Any]] = list(records)

    @classmethod
    def from_sample_context(cls, context: dict[str, Any]) -> "RuntimeEvidenceIndex":
        rows: list[dict[str, Any]] = []
        for source, value in (
            ("trace.jsonl", context.get("trace") or context.get("raw_trace") or []),
            ("events.jsonl", context.get("events") or context.get("raw_events") or []),
            ("wire.jsonl", context.get("wire") or []),
        ):
            if not isinstance(value, list):
                continue
            for line, item in enumerate(value, 1):
                if not isinstance(item, dict) or _is_delta(item):
                    continue
                rows.append(_normalize_record(source, line, item))
        return cls(rows)

    def manifest(self) -> dict[str, Any]:
        by_source: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for row in self.records:
            by_source[row["source"]] = by_source.get(row["source"], 0) + 1
            kind = str(row.get("kind") or row.get("record_type") or "unknown")
            by_kind[kind] = by_kind.get(kind, 0) + 1
        return {
            "record_count": len(self.records),
            "sources": by_source,
            "kinds": by_kind,
            "query": {
                "name": "grep_runtime_evidence",
                "arguments": {
                    "pattern": "regex or plain text",
                    "source": "optional filename filter",
                    "agent_id": "optional agent filter",
                    "limit": "optional integer <= 30",
                },
                "note": "Use this query before making claims about assignment, handoff, waits, or acceptance.",
            },
        }

    def grep(
        self,
        pattern: str,
        *,
        source: str | None = None,
        agent_id: str | None = None,
        limit: int = 12,
    ) -> dict[str, Any]:
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("pattern must be a non-empty string")
        if len(pattern) > 300:
            raise ValueError("pattern is limited to 300 characters")
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error:
            rx = re.compile(re.escape(pattern), re.IGNORECASE)
        limit = max(1, min(int(limit), 30))
        hits: list[EvidenceHit] = []
        for row in self.records:
            if source and row.get("source") != source:
                continue
            if agent_id and str(row.get("agent_id") or "") != agent_id:
                continue
            matched: list[str] = []
            for field in ("kind", "tool_name", "agent_id", "parent_agent_id", "arguments", "result", "content", "description", "record_type", "phase", "data", "response"):
                value = row.get(field)
                if value is not None and rx.search(_text(value)):
                    matched.append(field)
            if matched:
                hits.append(EvidenceHit(
                    evidence_id=str(row["evidence_id"]), source=str(row["source"]),
                    line=row.get("line"), kind=row.get("kind") or row.get("record_type"),
                    record=_clip_record(row), matched_fields=tuple(matched),
                ))
                if len(hits) >= limit:
                    break
        return {"pattern": pattern, "count": len(hits), "hits": [hit.to_dict() for hit in hits]}


def _is_delta(item: dict[str, Any]) -> bool:
    kind = str(item.get("kind") or item.get("event") or item.get("record_type") or "").lower()
    if "delta" in kind or kind == "llm:tool_call:created":
        return True
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    return "delta" in str(payload.get("type") or "").lower()


def _normalize_record(source: str, line: int, item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    function = payload.get("function") if isinstance(payload.get("function"), dict) else {}
    row: dict[str, Any] = {
        "evidence_id": f"{source}:{line}",
        "source": source,
        "line": line,
        "kind": item.get("kind") or item.get("event") or payload.get("type"),
        "timestamp": item.get("timestamp") or (item.get("time") or {}).get("timestamp"),
    }
    for key in ("agent_id", "parent_agent_id", "tool_call_id", "attempt_id", "tool_name", "description", "file_path", "arguments", "result", "content", "record_type", "phase", "data", "response"):
        value = item.get(key)
        if value is None:
            value = payload.get(key)
        if value is not None:
            row[key] = value
    if function.get("name") is not None:
        row["tool_name"] = function["name"]
    if "arguments" not in row and function.get("arguments") is not None:
        row["arguments"] = function["arguments"]
    return row


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _clip_record(row: dict[str, Any], limit: int = 5000) -> dict[str, Any]:
    result: dict[str, Any] = {}
    total = 0
    for key, value in row.items():
        if key == "evidence_id":
            result[key] = value
            continue
        text = _text(value)
        if len(text) > 2500:
            value = text[:2500] + "\n[truncated]"
        cost = len(_text(value))
        if total + cost > limit and result:
            break
        result[key] = value
        total += cost
    return result
