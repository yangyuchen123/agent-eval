"""Runtime-neutral evidence catalog for archived attempts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .evidence import EvidenceProvider, _filter_records, _rank_records, _record_text
from .models import EvidenceQuery, EvidenceRecord


def _xlsx_sheets(path: Path) -> dict[str, Any]:
    """Project an .xlsx workbook into bounded sheet grids using only stdlib.

    openpyxl may be unavailable offline; zipfile + ElementTree cover the
    common OOXML layout (shared strings, workbook rels, per-sheet rows).
    Formulas are surfaced as ``=...`` strings so the Judge can verify both
    values and formula structure.
    """
    import zipfile
    import xml.etree.ElementTree as ET

    NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    P = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        if "xl/workbook.xml" not in names:
            return {}
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        sheet_rids = [
            (s.get("name") or "", s.get(R + "id"))
            for s in wb.findall(".//m:sheets/m:sheet", NS)
        ]
        rels: dict[str, str] = {}
        if "xl/_rels/workbook.xml.rels" in names:
            r = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            for rel in r.findall(f"{P}Relationship"):
                rels[rel.get("Id") or ""] = rel.get("Target") or ""
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            ss = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss.findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        result: dict[str, Any] = {}
        for name, rid in sheet_rids:
            target = rels.get(rid or "")
            if not target:
                continue
            part = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
            part = "/".join(p for p in part.split("/") if p not in {"", ".", ".."})
            if part not in names:
                continue
            sheet = ET.fromstring(zf.read(part))
            grid: list[Any] = []
            for row in sheet.findall(".//m:sheetData/m:row", NS):
                cells: dict[str, Any] = {}
                for c in row.findall("m:c", NS):
                    ref = c.get("r") or ""
                    v = c.find("m:v", NS)
                    t = c.get("t")
                    value: Any = v.text if v is not None else None
                    if t == "s" and value is not None:
                        try:
                            value = shared[int(value)]
                        except (ValueError, IndexError, TypeError):
                            pass
                    f = c.find("m:f", NS)
                    if f is not None:
                        value = f"={f.text or ''}"
                    cells[ref] = value
                if cells:
                    grid.append(cells)
                if len(grid) >= 40:
                    break
            result[name] = grid
        return result


def _xlsx_projection(path: Path) -> tuple[dict[str, Any], bool]:
    """(projection, projected_ok) — prefer openpyxl, fall back to stdlib."""
    try:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        sheets = {ws.title: [list(row) for row in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
        wb.close()
        return {"workbook_sheets": sheets, "format": "xlsx"}, True
    except Exception:  # noqa: BLE001
        try:
            return {"workbook_sheets": _xlsx_sheets(path), "format": "xlsx"}, True
        except Exception:  # noqa: BLE001
            return {}, False


class EvidenceCatalog(EvidenceProvider):
    """In-memory, runtime-neutral searchable environment.

    This class deliberately provides generic search/navigation only. It does
    not know what a rubric question means and never synthesizes a prepared
    evidence packet or a handoff verdict.
    """

    def __init__(self, records: Iterable[EvidenceRecord] = ()):
        self.records = list(records)
        self._by_id = {record.evidence_id: record for record in self.records}
        self._query_log: list[dict[str, Any]] = []

    @classmethod
    def from_attempt_dir(cls, attempt_dir: str | Path) -> "EvidenceCatalog":
        root = Path(attempt_dir)
        records: list[EvidenceRecord] = []
        for filename in ("trace.jsonl", "events.jsonl", "wire.jsonl"):
            path = root / filename
            if not path.is_file():
                continue
            for line, item in _jsonl(path):
                if _is_stream_delta(item):
                    continue
                record = _normalize(filename, line, item)
                if record is not None:
                    records.append(record)
        # Index persisted workspace artifacts as first-class evidence.  Text
        # files are searchable directly; common XLSX artifacts get a bounded
        # value-level projection so the independent Judge can verify workbook
        # contents without receiving the project scorer's result.
        workspace = root / "skill_workspace"
        if workspace.is_dir():
            for path in sorted(p for p in workspace.rglob("*") if p.is_file()):
                rel = path.relative_to(root).as_posix()
                content: dict[str, Any] = {"file_path": rel, "size_bytes": path.stat().st_size}
                try:
                    if path.suffix.lower() == ".xlsx":
                        projection, ok = _xlsx_projection(path)
                        content.update(projection)
                        if not ok:
                            content["projection_error"] = "xlsx projection failed"
                    else:
                        content["text"] = path.read_text(encoding="utf-8", errors="replace")
                except Exception as exc:  # preserve artifact presence even if projection fails
                    content["projection_error"] = repr(exc)
                records.append(EvidenceRecord(
                    evidence_id=f"octagon:artifact:{rel}", source="skill_workspace",
                    event_type="artifact_file", kind="artifact",
                    evidence_class="artifact_observation", claim_strength="direct",
                    file_path=rel, content=content,
                ))
        _attach_relations(records)
        return cls(records)

    @classmethod
    def from_harbor_trial(cls, trial_dir: str | Path) -> "EvidenceCatalog":
        """Build runtime-neutral evidence from Harbor ATIF plus artifacts."""
        root = Path(trial_dir)
        records: list[EvidenceRecord] = []
        trajectory_path = root / "agent" / "trajectory.json"
        if trajectory_path.is_file():
            payload = json.loads(trajectory_path.read_text(encoding="utf-8"))
            agent = payload.get("agent") or {} if isinstance(payload, dict) else {}
            agent_id = str(agent.get("name") or root.name)
            for index, step in enumerate((payload.get("steps") or []) if isinstance(payload, dict) else [], 1):
                if not isinstance(step, dict):
                    continue
                step_id = str(step.get("step_id") or index)
                timestamp = step.get("timestamp")
                source = str(step.get("source") or "unknown")
                message_id = f"harbor:step:{step_id}:message"
                if step.get("message") is not None:
                    records.append(EvidenceRecord(
                        evidence_id=message_id, source="agent/trajectory.json", line=index,
                        event_type=f"{source}_message", kind="message",
                        evidence_class="direct_runtime_event", claim_strength="direct",
                        agent_id=agent_id, actor_agent_id=agent_id if source == "agent" else source,
                        message_id=message_id, timestamp=timestamp,
                        content={"role": source, "message": step.get("message")},
                    ))
                results = {
                    str(row.get("source_call_id") or ""): row
                    for row in ((step.get("observation") or {}).get("results") or [])
                    if isinstance(row, dict)
                }
                for call_index, call in enumerate(step.get("tool_calls") or [], 1):
                    if not isinstance(call, dict):
                        continue
                    call_id = str(call.get("tool_call_id") or f"step-{step_id}-call-{call_index}")
                    call_eid = f"harbor:step:{step_id}:call:{call_id}"
                    result_eid = f"harbor:step:{step_id}:result:{call_id}"
                    result = results.get(call_id)
                    records.append(EvidenceRecord(
                        evidence_id=call_eid, source="agent/trajectory.json", line=index,
                        event_type="tool_call", kind="tool_call",
                        evidence_class="direct_runtime_event", claim_strength="direct",
                        agent_id=agent_id, actor_agent_id=agent_id, tool_name=call.get("function_name"),
                        tool_call_id=call_id, message_id=message_id, timestamp=timestamp,
                        content={"arguments": call.get("arguments")},
                        related_evidence=[result_eid] if result is not None else [],
                    ))
                    if result is not None:
                        records.append(EvidenceRecord(
                            evidence_id=result_eid, source="agent/trajectory.json", line=index,
                            event_type="tool_result", kind="tool_result",
                            evidence_class="direct_runtime_event", claim_strength="direct",
                            agent_id=agent_id, actor_agent_id="environment", target_agent_id=agent_id,
                            tool_name=call.get("function_name"), tool_call_id=call_id,
                            message_id=message_id, timestamp=timestamp,
                            content={"result": result.get("content")},
                            related_evidence=[call_eid],
                        ))
        artifacts_root = root / "artifacts"
        if artifacts_root.is_dir():
            for path in sorted(p for p in artifacts_root.rglob("*") if p.is_file() and p.name != "manifest.json"):
                rel = path.relative_to(artifacts_root).as_posix()
                content: dict[str, Any] = {"file_path": rel, "size_bytes": path.stat().st_size}
                try:
                    if path.suffix.lower() == ".xlsx":
                        projection, ok = _xlsx_projection(path)
                        content.update(projection)
                        if not ok:
                            content["projection_error"] = "xlsx projection failed"
                    else:
                        content["text"] = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                records.append(EvidenceRecord(
                    evidence_id=f"harbor:artifact:{rel}", source="artifacts",
                    event_type="artifact_file", kind="artifact",
                    evidence_class="artifact_observation", claim_strength="direct",
                    file_path=rel, content=content,
                ))
        _attach_relations(records)
        return cls(records)

    def _log(self, operation: str, **payload: Any) -> None:
        self._query_log.append({"operation": operation, **payload})

    def search(self, query: EvidenceQuery) -> list[EvidenceRecord]:
        result = _rank_records(_filter_records(self.records, query), query.text)
        result = result[: query.limit]
        self._log("search", query=query.model_dump(), result_ids=[r.evidence_id for r in result])
        return result

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        result = self._by_id.get(evidence_id)
        self._log("get", evidence_id=evidence_id, result_ids=[evidence_id] if result else [])
        return result

    def call_context(self, tool_call_id: str) -> list[EvidenceRecord]:
        direct = [r for r in self.records if r.tool_call_id == tool_call_id]
        related_ids = {rid for record in direct for rid in record.related_evidence}
        related = [r for r in self.records if r.evidence_id in related_ids]
        result = _ordered_unique(direct + related)
        self._log("call_context", tool_call_id=tool_call_id, result_ids=[r.evidence_id for r in result])
        return result

    def related(self, evidence_id: str, relation: str) -> list[EvidenceRecord]:
        source = self.get(evidence_id)
        if source is None:
            self._log("related", evidence_id=evidence_id, relation=relation, result_ids=[])
            return []

        result: list[EvidenceRecord] = []
        if relation in {"same_call", "call"} and source.tool_call_id:
            result = [r for r in self.records if r.tool_call_id == source.tool_call_id]
        elif relation in {"same_agent", "agent"} and (source.agent_id or source.actor_agent_id):
            actor = source.actor_agent_id or source.agent_id
            result = [r for r in self.records if actor in {r.agent_id, r.actor_agent_id, r.target_agent_id}]
        elif relation == "parent" and source.parent_agent_id:
            result = [r for r in self.records if source.parent_agent_id in {r.agent_id, r.actor_agent_id}]
        elif relation == "child" and (source.agent_id or source.actor_agent_id):
            actor = source.actor_agent_id or source.agent_id
            result = [r for r in self.records if r.parent_agent_id == actor]
        elif relation in {"before", "after"}:
            if source.timestamp:
                result = [
                    r for r in self.records
                    if r.timestamp and ((r.timestamp < source.timestamp) if relation == "before" else (r.timestamp > source.timestamp))
                ]
        elif relation in {"related_message", "message"} and source.message_id:
            result = [r for r in self.records if r.message_id == source.message_id]
        elif relation in {"artifact", "related", "downstream"}:
            result = [r for r in self.records if source.evidence_id in r.related_evidence]

        result = _ordered_unique(result)
        self._log("related", evidence_id=evidence_id, relation=relation, result_ids=[r.evidence_id for r in result])
        return result

    def query_trajectory(self) -> list[dict[str, Any]]:
        """Return the Judge's generic search/navigation history for analysis."""
        return list(self._query_log)

    def manifest(self) -> dict[str, Any]:
        sources: dict[str, int] = {}
        kinds: dict[str, int] = {}
        fields = {"arguments": 0, "result": 0, "content": 0, "tool_call_id": 0, "agent_id": 0}
        for record in self.records:
            sources[record.source] = sources.get(record.source, 0) + 1
            key = record.event_type or record.kind or "unknown"
            kinds[key] = kinds.get(key, 0) + 1
            for field in fields:
                if field in record.content or getattr(record, field, None):
                    fields[field] += 1
        return {"record_count": len(self.records), "sources": sources, "kinds": kinds, "semantic_field_counts": fields}


def _jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    rows = []
    for line, text in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not text.strip():
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append((line, value))
    return rows


def _is_stream_delta(item: dict[str, Any]) -> bool:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    kind = str(item.get("kind") or item.get("event") or item.get("record_type") or "").lower()
    return (
        "delta" in kind
        or kind == "llm:tool_call:created"
        or "delta" in str(payload.get("type") or "").lower()
        or "arguments_delta" in item
        or "arguments_delta" in payload
    )


def _normalize(source: str, line: int, item: dict[str, Any]) -> EvidenceRecord | None:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    correlation = item.get("correlation") if isinstance(item.get("correlation"), dict) else {}
    time_data = item.get("time") if isinstance(item.get("time"), dict) else {}
    function = payload.get("function") if isinstance(payload.get("function"), dict) else {}
    event_type = str(item.get("event_type") or item.get("kind") or item.get("event") or item.get("record_type") or payload.get("type") or data.get("event") or "")
    tool_name = item.get("tool_name") or payload.get("tool_name") or data.get("tool_name") or function.get("name")
    tool_call_id = item.get("tool_call_id") or payload.get("tool_call_id") or data.get("tool_call_id") or correlation.get("logical_call_id")
    message_id = item.get("message_id") or payload.get("message_id") or data.get("message_id") or correlation.get("turn_id")
    actor_agent_id = (item.get("actor_agent_id") or item.get("agent_id") or payload.get("actor_agent_id")
                      or payload.get("agent_id") or correlation.get("agent_id"))
    target_agent_id = item.get("target_agent_id") or payload.get("target_agent_id") or data.get("target_agent_id")
    parent_agent_id = (item.get("parent_agent_id") or payload.get("parent_agent_id")
                       or correlation.get("parent_agent_id") or payload.get("parent_fork_tool_call_id"))
    file_path = item.get("file_path") or payload.get("file_path") or data.get("file_path")
    lifecycle_state = item.get("lifecycle_state") or payload.get("lifecycle_state") or data.get("status")

    content: dict[str, Any] = {}
    for key in (
        "tool_name", "arguments", "result", "content", "description", "record_type", "phase",
        "data", "response", "ok", "error", "file_path", "message", "prompt", "write_scope",
        "expected_output",
    ):
        value = item.get(key)
        if value is None:
            value = payload.get(key)
        if value is not None:
            content[key] = value
    if tool_name is not None:
        content["tool_name"] = tool_name
    if "arguments" not in content and function.get("arguments") is not None:
        content["arguments"] = function["arguments"]
    if file_path is not None:
        content["file_path"] = file_path
    if data:
        # Preserve the complete semantic wire payload. It is searchable and
        # retrievable through tools, but is not eagerly placed in the prompt.
        content.setdefault("data", data)
    if correlation:
        content.setdefault("correlation", correlation)

    evidence_class = "direct_runtime_event" if source in {"trace.jsonl", "events.jsonl"} else "derived_runtime_relation"
    if event_type in {"workspace:changed", "artifact:changed"}:
        evidence_class = "artifact_observation"
    if str(tool_name or "") == "Write" and "coordination_log" in json.dumps(content, ensure_ascii=False, default=str):
        evidence_class = "retrospective_artifact"
    timestamp = item.get("timestamp") or time_data.get("timestamp")
    return EvidenceRecord(
        evidence_id=f"{source}:{line}", source=source, line=line,
        event_type=event_type or None, kind=event_type or None,
        evidence_class=evidence_class,
        claim_strength="direct" if evidence_class == "direct_runtime_event" else "indirect",
        actor_agent_id=str(actor_agent_id) if actor_agent_id is not None else None,
        agent_id=str(actor_agent_id) if actor_agent_id is not None else None,
        target_agent_id=str(target_agent_id) if target_agent_id is not None else None,
        parent_agent_id=str(parent_agent_id) if parent_agent_id is not None else None,
        tool_name=str(tool_name) if tool_name is not None else None,
        tool_call_id=str(tool_call_id) if tool_call_id is not None else None,
        message_id=str(message_id) if message_id is not None else None,
        timestamp=str(timestamp) if timestamp is not None else None,
        file_path=str(file_path) if file_path is not None else None,
        lifecycle_state=str(lifecycle_state) if lifecycle_state is not None else None,
        content=content,
    )


def _attach_relations(records: list[EvidenceRecord]) -> None:
    by_call: dict[str, list[str]] = {}
    by_agent: dict[str, list[str]] = {}
    for record in records:
        if record.tool_call_id:
            by_call.setdefault(record.tool_call_id, []).append(record.evidence_id)
        for agent in {record.agent_id, record.actor_agent_id, record.target_agent_id} - {None}:
            by_agent.setdefault(agent, []).append(record.evidence_id)
    for record in records:
        related = list(record.related_evidence)
        if record.tool_call_id:
            related.extend(by_call.get(record.tool_call_id, []))
        for agent in {record.agent_id, record.actor_agent_id, record.target_agent_id} - {None}:
            related.extend(by_agent.get(agent, [])[:20])
        record.related_evidence = list(dict.fromkeys(x for x in related if x != record.evidence_id))


def _ordered_unique(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    return list({record.evidence_id: record for record in records}.values())
