"""Deterministic artifact summaries for RRD evaluators.

GDPval and other deliverable-centric tasks must judge the artifact, not the
agent's self-report. Runtrace is intentionally not handled here; callers that
want process evidence pass it separately.

XLSX parsing uses the standard library so the protocol does not depend on
openpyxl being installed in the evaluator environment.
"""
from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


XLSX_SUFFIXES = {".xlsx", ".xlsm"}
DEFAULT_MAX_SHEETS = None
DEFAULT_MAX_ROWS = None
DEFAULT_MAX_COLS = None
DEFAULT_MAX_CHARS = None
NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _cell_preview(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").strip()


def _col_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for ch in letters.upper():
        index = index * 26 + (ord(ch) - 64)
    return max(0, index - 1)


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values = []
    for item in root.findall("m:si", NS):
        texts = [node.text or "" for node in item.findall(".//m:t", NS)]
        values.append("".join(texts))
    return values


def _sheet_targets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = {}
    try:
        rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        for rel in rel_root:
            rels[rel.attrib.get("Id")] = rel.attrib.get("Target", "")
    except KeyError:
        rels = {}
    sheets = []
    for sheet in workbook.findall("m:sheets/m:sheet", NS):
        name = sheet.attrib.get("name") or "Sheet"
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = (rels.get(rel_id) or "").lstrip("/")
        if target and not target.startswith("xl/"):
            target = "xl/" + target
        if name and target:
            sheets.append((name, target))
    return sheets


def _sheet_preview(zf: zipfile.ZipFile, target: str, shared: list[str], *, max_rows: int | None, max_cols: int | None) -> dict[str, Any]:
    root = ET.fromstring(zf.read(target))
    rows: dict[int, dict[int, str]] = {}
    formula_count = 0
    for cell in root.findall("m:sheetData/m:row/m:c", NS):
        ref = cell.attrib.get("r") or ""
        if not ref:
            continue
        row_idx = int("".join(ch for ch in ref if ch.isdigit()) or "0")
        col_idx = _col_index(ref)
        if row_idx < 1:
            continue
        if max_rows is not None and row_idx > max_rows:
            continue
        if max_cols is not None and col_idx >= max_cols:
            continue
        formula = cell.find("m:f", NS)
        value_node = cell.find("m:v", NS)
        raw = None
        if formula is not None and (formula.text or "").strip():
            raw = "=" + formula.text.strip()
            formula_count += 1
        elif value_node is not None and value_node.text is not None:
            raw = value_node.text
            if cell.attrib.get("t") == "s":
                try:
                    raw = shared[int(raw)]
                except (ValueError, IndexError):
                    pass
        if raw is None:
            inline = cell.find("m:is", NS)
            if inline is not None:
                raw = "".join(node.text or "" for node in inline.findall(".//m:t", NS))
        if raw is None:
            continue
        rows.setdefault(row_idx, {})[col_idx] = _cell_preview(raw)
    preview = []
    for row_idx in sorted(rows):
        width = max(rows[row_idx]) + 1 if rows[row_idx] else 0
        limit = width if max_cols is None else min(width, max_cols)
        preview.append([rows[row_idx].get(i, "") for i in range(limit)])
    headers = preview[0] if preview else []
    return {
        "header_preview": headers,
        "row_preview_count": len(preview),
        "formula_count_in_preview": formula_count,
        "preview_rows": preview,
    }


def summarize_xlsx(
    path: str | Path,
    *,
    max_sheets: int | None = DEFAULT_MAX_SHEETS,
    max_rows: int | None = DEFAULT_MAX_ROWS,
    max_cols: int | None = DEFAULT_MAX_COLS,
) -> dict[str, Any]:
    """Extract every sheet and every cell the workbook actually contains."""
    file_path = Path(path)
    if not file_path.exists():
        return {"path": str(file_path), "status": "missing", "suffix": file_path.suffix.lower()}
    try:
        with zipfile.ZipFile(file_path) as zf:
            shared = _shared_strings(zf)
            sheets = []
            targets = _sheet_targets(zf)
            if max_sheets is not None:
                targets = targets[:max_sheets]
            for name, target in targets:
                try:
                    preview = _sheet_preview(zf, target, shared, max_rows=max_rows, max_cols=max_cols)
                except KeyError:
                    preview = {
                        "header_preview": [],
                        "row_preview_count": 0,
                        "formula_count_in_preview": 0,
                        "preview_rows": [],
                    }
                sheets.append({"name": name, **preview})
    except Exception as exc:
        return {"path": str(file_path), "status": "unreadable", "reason": repr(exc)}
    return {
        "path": str(file_path),
        "status": "present",
        "suffix": file_path.suffix.lower(),
        "sheet_names": [x["name"] for x in sheets],
        "sheet_count": len(sheets),
        "sheets": sheets,
    }


def summarize_artifact_path(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix in XLSX_SUFFIXES:
        return summarize_xlsx(file_path)
    if not file_path.exists():
        return {"path": str(file_path), "status": "missing", "suffix": suffix}
    return {
        "path": str(file_path),
        "status": "present",
        "suffix": suffix,
        "size_bytes": file_path.stat().st_size,
        "note": "non-xlsx artifact; evaluator receives path and size only",
    }


def render_artifact_text(summaries: list[dict[str, Any]], *, max_chars: int | None = DEFAULT_MAX_CHARS, compact: bool = False) -> str:
    if not summaries:
        return ""
    import json
    if compact:
        lines = []
        for item in summaries:
            lines.append(f"path\t{item.get('path')}")
            lines.append(f"status\t{item.get('status')}")
            for sheet in item.get("sheets") or []:
                lines.append(f"## {sheet.get('name')}")
                for row in sheet.get("preview_rows") or []:
                    lines.append("\t".join(str(cell) for cell in row))
        text = "\n".join(lines)
    else:
        text = json.dumps(summaries, ensure_ascii=False, indent=2)
    if max_chars is None or len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + "\n...[truncated]..."


def collect_artifact_paths(value: dict[str, Any], nested: dict[str, Any] | None = None) -> list[str]:
    raw = value.get("artifact_paths")
    if raw is None and nested:
        raw = nested.get("artifact_paths")
    if raw is None:
        raw = (value.get("metadata") or {}).get("artifact_paths") if isinstance(value.get("metadata"), dict) else None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if str(x).strip()]
