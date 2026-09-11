"""Deterministic inspection of an Excel workbook.

This is the file-native evidence channel for GDPval-style tasks.  It reads the
.xlsx itself (stdlib zip/xml) and optionally LibreOffice-evaluated values.
It does not score rubric items.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

XLSX_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
ODS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
ODS_OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
EXCEL_EPOCH = datetime(1899, 12, 30)
BUILTIN_NUM_FMTS = {
    "14": "m/d/yy",
    "15": "d-mmm-yy",
    "16": "d-mmm",
    "17": "mmm-yy",
    "22": "m/d/yy h:mm",
}


def col_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for ch in letters.upper():
        index = index * 26 + (ord(ch) - 64)
    return max(0, index - 1)


def col_letter(index: int) -> str:
    n = index + 1
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def excel_serial_date(value: str) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 20000 or number > 80000:
        return None
    try:
        return (EXCEL_EPOCH + timedelta(days=number)).date().isoformat()
    except OverflowError:
        return None


def inspect_xlsx(path: str | Path, *, max_preview_rows: int = 8) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {"path": str(file_path), "status": "missing"}
    try:
        with zipfile.ZipFile(file_path) as zf:
            shared = _shared_strings(zf)
            styles = _styles(zf)
            sheets = []
            for name, target in _sheet_targets(zf):
                sheets.append(_sheet_inspect(zf, name, target, shared, styles, max_preview_rows=max_preview_rows))
    except Exception as exc:
        return {"path": str(file_path), "status": "unreadable", "reason": repr(exc)}
    return {
        "path": str(file_path),
        "status": "present",
        "suffix": file_path.suffix.lower(),
        "size_bytes": file_path.stat().st_size,
        "sheet_count": len(sheets),
        "sheet_names": [s["name"] for s in sheets],
        "excel_name_limit_31": [s["name"] for s in sheets if len(s["name"]) >= 31],
        "sheets": sheets,
    }


def render_inspect_text(inspect: MappingLike) -> str:
    inspect = dict(inspect)
    lines = [
        f"path\t{inspect.get('path')}",
        f"status\t{inspect.get('status')}",
        f"sheet_count\t{inspect.get('sheet_count')}",
        f"sheet_names\t{json.dumps(inspect.get('sheet_names') or [], ensure_ascii=False)}",
        f"excel_name_limit_31\t{json.dumps(inspect.get('excel_name_limit_31') or [], ensure_ascii=False)}",
        "",
    ]
    for sheet in inspect.get("sheets") or []:
        lines.append(f"## {sheet.get('name')}  (len={len(str(sheet.get('name') or ''))})")
        lines.append(f"dimension\t{sheet.get('dimension')}")
        lines.append(f"xml_rows\t{sheet.get('xml_row_count')} formulas\t{sheet.get('formula_count')} cached_values\t{sheet.get('cached_formula_value_count')}")
        lines.append(f"headers\t{json.dumps(sheet.get('headers') or [], ensure_ascii=False)}")
        lines.append("preview:")
        for row in sheet.get("preview") or []:
            cells = []
            for cell in row:
                addr = cell.get("ref")
                shown = cell.get("display") or cell.get("value") or cell.get("formula") or ""
                cells.append(f"{addr}={shown}")
            lines.append("  " + " | ".join(cells[:16]))
        lines.append("")
    return "\n".join(lines)


MappingLike = dict[str, Any]


def evaluate_with_libreoffice(path: str | Path, *, timeout: int = 90) -> dict[str, Any]:
    """Convert xlsx → ODS via soffice and read calculated values.

    The source xlsx for this GDPval attempt stores formulas without cached
    ``<v>`` values.  LibreOffice evaluation is the deterministic way to see
    computed numbers without asking the LLM to execute Excel.
    """
    file_path = Path(path)
    soffice = _which("soffice")
    if not soffice:
        return {"status": "skipped", "reason": "soffice_not_found"}
    with tempfile.TemporaryDirectory(prefix="workbook_eval_") as raw:
        tmp = Path(raw)
        profile = tmp / "profile"
        out = tmp / "out"
        profile.mkdir()
        out.mkdir()
        cmd = [
            soffice, "--headless", "--norestore",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to", "ods", "--outdir", str(out), str(file_path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
        except Exception as exc:
            return {"status": "failed", "reason": repr(exc)}
        ods = next(out.glob("*.ods"), None)
        if ods is None:
            return {"status": "failed", "reason": "no_ods_written"}
        return {"status": "evaluated", "tables": _parse_ods(ods)}


def _which(name: str) -> str | None:
    from shutil import which
    return which(name)


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values = []
    for item in root.findall("m:si", XLSX_NS):
        texts = [node.text or "" for node in item.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")]
        if not texts:
            texts = [node.text or "" for node in item.findall(".//m:t", XLSX_NS)]
        values.append("".join(texts))
    return values


def _styles(zf: zipfile.ZipFile) -> dict[str, Any]:
    try:
        root = ET.fromstring(zf.read("xl/styles.xml"))
    except KeyError:
        return {"num_fmts": {}, "cell_xfs": []}
    custom = {
        node.attrib.get("numFmtId"): node.attrib.get("formatCode")
        for node in root.findall("m:numFmts/m:numFmt", XLSX_NS)
    }
    xfs = [node.attrib.get("numFmtId") for node in root.findall("m:cellXfs/m:xf", XLSX_NS)]
    return {"num_fmts": {**BUILTIN_NUM_FMTS, **custom}, "cell_xfs": xfs}


def _sheet_targets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels: dict[str, str] = {}
    try:
        rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        for rel in rel_root:
            rels[rel.attrib.get("Id") or ""] = rel.attrib.get("Target") or ""
    except KeyError:
        pass
    sheets = []
    for sheet in workbook.findall("m:sheets/m:sheet", XLSX_NS):
        name = sheet.attrib.get("name") or "Sheet"
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = (rels.get(rel_id or "") or "").lstrip("/")
        if target and not target.startswith("xl/"):
            target = "xl/" + target
        if name and target:
            sheets.append((name, target))
    return sheets


def _sheet_inspect(
    zf: zipfile.ZipFile,
    name: str,
    target: str,
    shared: list[str],
    styles: dict[str, Any],
    *,
    max_preview_rows: int,
) -> dict[str, Any]:
    root = ET.fromstring(zf.read(target))
    dim = root.find("m:dimension", XLSX_NS)
    formula_count = 0
    cached = 0
    value_only = 0
    by_row: dict[int, list[dict[str, Any]]] = {}
    for cell in root.findall("m:sheetData/m:row/m:c", XLSX_NS):
        ref = cell.attrib.get("r") or ""
        if not ref:
            continue
        row_idx = int("".join(ch for ch in ref if ch.isdigit()) or "0")
        formula_node = cell.find("m:f", XLSX_NS)
        value_node = cell.find("m:v", XLSX_NS)
        formula = (formula_node.text or "").strip() if formula_node is not None else ""
        raw_value = value_node.text if value_node is not None else None
        cell_type = cell.attrib.get("t")
        style_idx = cell.attrib.get("s")
        num_fmt = None
        if style_idx is not None:
            try:
                num_fmt_id = (styles.get("cell_xfs") or [])[int(style_idx)]
                num_fmt = (styles.get("num_fmts") or {}).get(num_fmt_id)
            except (ValueError, IndexError):
                num_fmt = None
        display = None
        if formula:
            formula_count += 1
            if raw_value is not None:
                cached += 1
        elif raw_value is not None:
            value_only += 1
            if cell_type == "s":
                try:
                    display = shared[int(raw_value)]
                except (ValueError, IndexError):
                    display = raw_value
            else:
                display = raw_value
                as_date = excel_serial_date(raw_value)
                if as_date and num_fmt and any(token in (num_fmt or "").lower() for token in ("d", "y", "m")):
                    display = f"{raw_value} (serial→{as_date})"
        record = {
            "ref": ref,
            "formula": f"={formula}" if formula else None,
            "value": raw_value,
            "display": display,
            "type": cell_type,
            "num_fmt": num_fmt,
        }
        by_row.setdefault(row_idx, []).append(record)
    preview_rows = []
    for row_idx in sorted(by_row)[:max_preview_rows]:
        preview_rows.append(by_row[row_idx])
    header_displays = []
    if by_row:
        first = by_row[min(by_row)]
        header_displays = [c.get("display") or c.get("formula") or "" for c in first]
    # Heuristic header: the first row that has several non-empty text cells.
    headers = _guess_headers(by_row)
    return {
        "name": name,
        "name_length": len(name),
        "dimension": dim.attrib.get("ref") if dim is not None else None,
        "xml_row_count": len(by_row),
        "formula_count": formula_count,
        "cached_formula_value_count": cached,
        "value_only_count": value_only,
        "headers": headers,
        "first_row": header_displays,
        "preview": preview_rows,
    }


def _guess_headers(by_row: dict[int, list[dict[str, Any]]]) -> list[str]:
    best: list[str] = []
    best_score = -1
    for row_idx in sorted(by_row)[:6]:
        labels = []
        score = 0
        for cell in by_row[row_idx]:
            text = str(cell.get("display") or "")
            labels.append(text)
            if text and not cell.get("formula"):
                score += 1
        if score > best_score:
            best_score = score
            best = labels
    return best


def _parse_ods(path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("content.xml"))
    tables = []
    for table in root.findall(f".//{{{ODS_TABLE}}}table"):
        name = table.attrib.get(f"{{{ODS_TABLE}}}name")
        rows = []
        for row in table.findall(f"{{{ODS_TABLE}}}table-row"):
            cells: list[str] = []
            for cell in list(row):
                if not (cell.tag.endswith("table-cell") or cell.tag.endswith("covered-table-cell")):
                    continue
                repeat = int(cell.attrib.get(f"{{{ODS_TABLE}}}number-columns-repeated") or 1)
                value = cell.attrib.get(f"{{{ODS_OFFICE}}}value")
                text = "".join(cell.itertext()).strip()
                shown = text or value or ""
                if repeat > 40:
                    if shown:
                        cells.append(shown)
                    break
                cells.extend([shown] * min(repeat, 24))
                if len(cells) > 24:
                    cells = cells[:24]
                    break
            if any(cells):
                rows.append(cells)
        tables.append({"name": name, "row_count": len(rows), "rows": rows[:80]})
    return tables
