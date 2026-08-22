"""JSON / digest / atomic-write helpers (dependency-free)."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

JSON_OPTS = {"ensure_ascii": False, "indent": 2}


def read_json(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def atomic_write_json(path: str | Path, value: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, **JSON_OPTS)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def value_digest(value: Any) -> str:
    """Stable digest of an arbitrary JSON-able value."""
    return hashlib.sha256(_json_bytes(value)).hexdigest()[:32]


def file_digest(path: str | Path, include_sha256: bool = False) -> dict[str, str]:
    """Lightweight fingerprint of a file (size + mtime + optional sha256)."""
    path = Path(path)
    stat = path.stat()
    digest = {
        "size": str(stat.st_size),
        "mtime_ns": str(stat.st_mtime_ns),
    }
    if include_sha256:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        digest["sha256"] = h.hexdigest()
    return digest
