"""Pi-backed workbook Judge: inspect the real xlsx, not a compact TSV.

Protocol id: ``workbook_pi_judge.v1``

This replaces the env-local BladeAgent session in
``gdpval-prepaid-amortization-official/judge_local.py`` with a Pi coding-agent
session.  AgentEval still only sees JudgeRequest / JudgeResponse; Pi is the
Judge harness, not a production scoring entrypoint inside AgentEval.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from .gdpval_result import normalize_official_result, parse_model_json, repair_rubric_ids, score_100
from .workbook import evaluate_with_libreoffice, inspect_xlsx, render_inspect_text

PROTOCOL_ID = "workbook_pi_judge.v1"
PROMPT_VERSION = "workbook_pi_judge.v1"
RESULT_FILE = "judge_result.json"
DEFAULT_PI = "pi"
DEFAULT_PROVIDER = "llm2"
DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_TIMEOUT = 900

SYSTEM_PROMPT = """You are an independent GDPval workbook judge running inside Pi.
You grade a real Excel deliverable against official binary rubric items.

Rules:
- Inspect the actual xlsx with read/bash. Do not judge from filenames or from any TSV dump.
- Do not modify uploaded files. Write only judge_result.json in this workspace.
- Use Python's zipfile/xml or, if present, inspect.json / evaluated.json produced before you started.
- Cite concrete sheet names, cell refs, formulas, and computed values in each reason.
- Grade STRICT BINARY: passed=true only when the criterion is fully satisfied; otherwise false. No partial credit.
- Do not use an expert/reference workbook. If one is present, ignore it.
- If a fact cannot be observed in the candidate workbook (or required source files), set passed=false and add the item id to unverified_items.
- After writing judge_result.json, stop. Do not keep exploring.
"""


def build_prompt(*, task_prompt: str, rubric: Sequence[Mapping[str, Any]], candidate_name: str, source_names: Sequence[str]) -> str:
    compact = [
        {
            "rubric_item_id": item["rubric_item_id"],
            "max_points": item["score"] if "score" in item else item.get("max_points"),
            "criterion": item["criterion"],
        }
        for item in rubric
    ]
    max_points = sum(int(item["max_points"]) for item in compact)
    sources = json.dumps(list(source_names), ensure_ascii=False)
    return f"""Grade the Agent Excel deliverable against every official rubric item.

Task prompt:
{task_prompt}

Workspace files:
- candidate/{candidate_name}  (the Agent workbook; this is what you grade)
- sources/                    (invoices and COA; {sources})
- inspect.json                (deterministic xlsx structure: sheet names, headers, formula counts, preview)
- inspect.txt                 (same, human-readable)
- evaluated.json              (LibreOffice-calculated values if soffice succeeded; may be status=skipped/failed)
- rubric/official_rubric.json

Procedure:
1. Read inspect.txt first. Confirm sheet names, including Excel's 31-character truncation.
2. If evaluated.json has status=evaluated, use those calculated numbers for amount/GL/roll-forward items. Do not invent cached formula values; the source xlsx may store formulas without <v>.
3. Open the xlsx (zip/xml or python) when you need a formula, a column, or a cell the summaries omit.
4. Use sources/ only for invoice completeness, amounts, dates, terms, and COA classification.
5. Grade all {len(compact)} items independently. passed=true only if fully satisfied.

Official rubric items:
{json.dumps(compact, ensure_ascii=False)}

Write the complete JSON to {RESULT_FILE} in the workspace root using the write tool. Do not put the full JSON only in chat.

JSON file structure:
{{
  "schema_version": "gdpval_rubric_judge.v1",
  "overall": {{
    "awarded_points": 0,
    "max_points": {max_points},
    "confidence": "high | medium | low",
    "summary": "concise overall assessment"
  }},
  "rubric_scores": [
    {{
      "rubric_item_id": "exact id from the rubric",
      "passed": false,
      "max_points": 0,
      "reason": "sheet/cell/formula evidence",
      "evidence_refs": ["Sheet!A1"]
    }}
  ],
  "unverified_items": [],
  "human_attention_points": []
}}
"""


def prepare_workspace(
    *,
    workspace: Path,
    candidate: Path,
    rubric_path: Path,
    source_files: Sequence[Path] = (),
    include_expert: bool = False,
    expert_workbook: Path | None = None,
    evaluate: bool = True,
) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    candidate_dir = workspace / "candidate"
    sources_dir = workspace / "sources"
    rubric_dir = workspace / "rubric"
    candidate_dir.mkdir(exist_ok=True)
    sources_dir.mkdir(exist_ok=True)
    rubric_dir.mkdir(exist_ok=True)
    dest = candidate_dir / candidate.name
    if dest.resolve() != candidate.resolve():
        shutil.copy2(candidate, dest)
    shutil.copy2(rubric_path, rubric_dir / "official_rubric.json")
    copied_sources = []
    for src in source_files:
        if src.is_file():
            shutil.copy2(src, sources_dir / src.name)
            copied_sources.append(src.name)
    if include_expert and expert_workbook and expert_workbook.is_file():
        ref = workspace / "reference"
        ref.mkdir(exist_ok=True)
        shutil.copy2(expert_workbook, ref / expert_workbook.name)
    inspect = inspect_xlsx(dest)
    (workspace / "inspect.json").write_text(json.dumps(inspect, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (workspace / "inspect.txt").write_text(render_inspect_text(inspect), encoding="utf-8")
    evaluated = {"status": "skipped", "reason": "evaluate_disabled"}
    if evaluate:
        evaluated = evaluate_with_libreoffice(dest)
    (workspace / "evaluated.json").write_text(json.dumps(evaluated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "candidate_name": dest.name,
        "source_names": copied_sources,
        "inspect": inspect,
        "evaluated_status": evaluated.get("status"),
        "include_expert": bool(include_expert and expert_workbook),
    }


def run_pi_judge(
    *,
    workspace: Path,
    prompt: str,
    provider: str | None = None,
    model: str | None = None,
    timeout: int | None = None,
    pi_bin: str | None = None,
    thinking: str = "off",
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    pi_bin = pi_bin or os.environ.get("PI_BIN") or DEFAULT_PI
    provider = provider or os.environ.get("PI_JUDGE_PROVIDER") or os.environ.get("JUDGE_PROVIDER") or DEFAULT_PROVIDER
    model = model or os.environ.get("PI_JUDGE_MODEL") or os.environ.get("JUDGE_MODEL") or DEFAULT_MODEL
    timeout = int(timeout or os.environ.get("PI_JUDGE_TIMEOUT") or DEFAULT_TIMEOUT)
    env = os.environ.copy()
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})
    cmd = [
        pi_bin, "-p", "--mode", "json", "--no-session",
        "--provider", provider, "--model", model,
        "--thinking", thinking,
        "--tools", "read,bash,grep,find,ls,write",
        "--exclude-tools", "edit",
        "--no-skills", "--no-prompt-templates", "--no-context-files",
        "--system-prompt", SYSTEM_PROMPT,
        prompt,
    ]
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(workspace),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    events_path = workspace / "pi_events.jsonl"
    events_path.write_text(proc.stdout or "", encoding="utf-8")
    (workspace / "pi_stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    (workspace / "pi_cmd.json").write_text(
        json.dumps({"cmd": cmd[:12] + ["<prompt>"], "returncode": proc.returncode, "provider": provider, "model": model}, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "returncode": proc.returncode,
        "latency_ms": int((time.time() - started) * 1000),
        "provider": provider,
        "model": model,
        "stdout_chars": len(proc.stdout or ""),
        "stderr_chars": len(proc.stderr or ""),
        "events_path": str(events_path),
    }


def collect_result(workspace: Path, rubric: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result_path = workspace / RESULT_FILE
    raw_text = ""
    source = "missing"
    if result_path.is_file():
        raw_text = result_path.read_text(encoding="utf-8")
        source = "workspace_file"
    else:
        raw_text = _last_assistant_text(workspace / "pi_events.jsonl")
        source = "pi_chat_fallback"
    if not raw_text.strip():
        return {"ok": False, "error": "Pi judge produced no JSON", "source": source}
    try:
        parsed = repair_rubric_ids(parse_model_json(raw_text), rubric)
        review = normalize_official_result(parsed, rubric)
        if parsed.get("id_repairs"):
            review["id_repairs"] = parsed["id_repairs"]
    except Exception as exc:
        (workspace / "judge_raw_response.txt").write_text(raw_text, encoding="utf-8")
        return {"ok": False, "error": f"parse/validation failed: {exc}", "source": source, "raw_preview": raw_text[:2000]}
    review["prompt_version"] = PROMPT_VERSION
    review["protocol"] = PROTOCOL_ID
    review["result_source"] = source
    (workspace / "judge_raw_response.txt").write_text(raw_text, encoding="utf-8")
    (workspace / RESULT_FILE).write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "score_100": score_100(review),
        "judge_review": review,
        "source": source,
    }


def _last_assistant_text(events_path: Path) -> str:
    if not events_path.is_file():
        return ""
    last = ""
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "message_end":
            continue
        message = event.get("message") or {}
        if message.get("role") != "assistant":
            continue
        parts = []
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                    parts.append(str(item.get("text") or item.get("content") or ""))
                elif isinstance(item, str):
                    parts.append(item)
        text = "\n".join(filter(None, parts)).strip()
        if text:
            last = text
    return last


def load_official_rubric(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("rubric_json") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise ValueError(f"official rubric_json missing in {path}")
    return [dict(x) for x in items if isinstance(x, dict)]
