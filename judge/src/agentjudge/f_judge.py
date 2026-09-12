"""F protocol: pi agent as judge.

Independent from the A/B protocols. F judge hands the rubric and a frozen
trial directory to a headless ``pi`` agent (read/bash tools), which
investigates the real artifacts itself and returns a structured judgment.
runtrace comes from pi's own session stream.

Endpoint: POST /v1/f-judge/evaluate
Protocol: ``F_agent_pi_judge`` (agent-eval.abcd.frozen.v1/F)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .models import JudgeRequest

PI_EXT = Path(__file__).resolve().parents[2] / "pi-ext" / "blade-provider.mjs"
SESSION_ROOT = Path(os.environ.get("JUDGE_SESSION_ROOT", "/tmp/pi-judge-sessions"))
PI_TIMEOUT = float(os.environ.get("F_JUDGE_TIMEOUT", "600"))


def _rubric_questions(request: JudgeRequest) -> list[dict[str, Any]]:
    rubric = request.rubric
    if isinstance(rubric, dict):
        return [dict(q) for q in (rubric.get("questions") or rubric.get("rubric_questions") or []) if isinstance(q, dict)]
    if request.rubric_question:
        return [dict(request.rubric_question)]
    return []


def _trial_dir(request: JudgeRequest) -> str | None:
    for ref in (request.trace_ref, request.artifact_ref):
        if isinstance(ref, dict) and ref.get("trial_dir"):
            return str(ref["trial_dir"])
    return None


def build_prompt(request: JudgeRequest) -> str:
    questions = _rubric_questions(request)
    trial = _trial_dir(request)
    lines = [
        "You are a strict evaluation judge. Investigate the real artifacts of the frozen trial below, "
        "then score each rubric question on 0..1 using the declared anchors.",
        "Use your tools (bash/read). Inspect the workspace artifacts (e.g. parse .xlsx with python3 zipfile, "
        "read text files), the agent trajectory (agent/trajectory.json) and the verifier output where present. "
        "Cite concrete evidence in every reason.",
        "Reply with ONLY a JSON object, no prose around it:",
    ]
    if trial:
        lines.append(f"trial_dir: {trial}")
    if questions:
        lines.append("Rubric questions:")
        for q in questions:
            lines.append(
                f"- id: {q.get('id')}\n"
                f"  question: {q.get('question')}\n"
                f"  anchors: {q.get('anchors')}\n"
                f"  evidence: {q.get('evidence')}"
            )
    lines.append(
        'JSON schema: {"question_judgments": [{"question_id": "<id>", "score": 0.0..1.0, '
        '"reason": "...", "status": "supported|contested"}], "overall_score": 0.0..1.0}'
    )
    return "\n\n".join(lines)


def _extract_final_json(trace: str) -> dict[str, Any]:
    """Take the last assistant text that parses as JSON from pi's JSONL stream."""
    for line in reversed(trace.splitlines()):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "message_end":
            continue
        message = event.get("message") or {}
        content = message.get("content") or []
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                text = str(block["text"]).strip()
                if text.startswith("{"):
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        continue
    return {}


def run_pi_judge(request: JudgeRequest) -> tuple[dict[str, Any], Path, str]:
    """Run the headless pi judge and return (payload, session_dir, trace)."""
    session_dir = SESSION_ROOT / f"f-judge-{uuid.uuid4().hex[:8]}"
    session_dir.mkdir(parents=True, exist_ok=True)
    prompt = build_prompt(request)
    provider = os.environ.get("F_JUDGE_PROVIDER", "blade")
    model = os.environ.get("F_JUDGE_MODEL") or os.environ.get("LLM_MODEL", "gpt-5.6-luna")
    pi_bin = os.environ.get("PI_BIN") or shutil.which("pi") or "pi"
    ext = PI_EXT if PI_EXT.is_file() else None
    cmd = [pi_bin, "-p", prompt, "--mode", "json", "--model", f"{provider}/{model}",
           "--session-dir", str(session_dir), "--no-session"]
    if ext is not None:
        cmd[1:1] = ["-e", str(ext)]
    env = os.environ.copy()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=PI_TIMEOUT, env=env)
    trace = proc.stdout or ""
    if proc.returncode != 0 and not trace:
        raise RuntimeError(f"pi judge failed (exit {proc.returncode}): {proc.stderr[-2000:]}")
    payload = _extract_final_json(trace)
    return payload, session_dir, trace


def f_response(request: JudgeRequest, payload: dict[str, Any], session_dir: Path, trace: str) -> dict[str, Any]:
    """Normalize pi output into the joint judgment response shape (F provenance)."""
    rows = payload.get("question_judgments") or []
    questions = _rubric_questions(request)
    question_judgments: list[dict[str, Any]] = []
    subscores: dict[str, float | None] = {}
    reasons: dict[str, str] = {}
    refs: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        qid = str(row.get("question_id") or "")
        score = row.get("score")
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError):
            score = None
        reason = str(row.get("reason") or "")
        if qid:
            subscores[qid] = score
            reasons[qid] = reason
        question_judgments.append({
            "question_id": qid,
            "score": score,
            "reason": reason,
            "status": row.get("status") or ("supported" if score is not None else "incomplete_evidence"),
            "evidence_refs": row.get("evidence_refs") or [],
        })
        refs.extend(row.get("evidence_refs") or [])
    # attach any rubric question pi omitted -> incomplete_evidence
    declared = {q.get("id") for q in questions}
    missing = sorted(declared - set(subscores))
    for qid in missing:
        subscores[qid] = None
        reasons[qid] = "(pi judge did not return this question)"
    overall = payload.get("overall_score")
    try:
        overall = float(overall) if overall is not None else None
    except (TypeError, ValueError):
        overall = None
    if overall is None and subscores:
        vals = [v for v in subscores.values() if v is not None]
        overall = round(sum(vals) / len(vals), 4) if vals else None
    trace_ref = str(session_dir / "pi-session.jsonl") if (session_dir / "pi-session.jsonl").is_file() else str(session_dir)
    status = "incomplete_evidence" if (missing or overall is None) else "scored"
    return {
        "schema_version": "agentjudge.joint_judgment.v1",
        "score": overall,
        "subscores": subscores,
        "reasons": reasons,
        "confidence": payload.get("confidence"),
        "evidence_refs": list(dict.fromkeys(refs)),
        "findings": question_judgments,
        "question_judgments": question_judgments,
        "provenance": {
            "model": f"{os.environ.get('F_JUDGE_PROVIDER', 'blade')}/{os.environ.get('F_JUDGE_MODEL') or os.environ.get('LLM_MODEL', 'gpt-5.6-luna')}",
            "protocol": "F_agent_pi_judge",
            "protocol_version": "agent-eval.abcd.frozen.v1/F",
            "judge": "pi",
            "pi_session": trace_ref,
            "trace_bytes": len(trace),
        },
        "status": status,
    }
