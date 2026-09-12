"""Judge panel HTTP service (agent-eval side).

Two separable parts behind one HTTP entry:

- Part 1 (plan + router): decide which judge backends evaluate a case+rubric.
  ``POST /v1/plan`` returns the decision only, for debugging routing.
- Part 2 (judge backends): actually score. ``POST /v1/judge/{f|b|single|deterministic}``
  hits one backend directly, bypassing plan/router for debugging.
- Full entry ``POST /v1/panel/evaluate``: plan -> run the selected backends ->
  weighted aggregation (score per rubric question + per-judge provenance).

B/F backends are forwarded to the standalone judge service (default
http://127.0.0.1:8787); deterministic runs locally (scorer path).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

JUDGE_URL = os.environ.get("PANEL_JUDGE_URL", "http://127.0.0.1:8787")

DEFAULT_WEIGHTS = {
    "deterministic": 1.0,
    "f_agent_pi_judge": 0.8,
    "b_llm_judge": 0.5,
    "single_rubric_judge": 0.4,
}


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------

def _post(url: str, payload: dict[str, Any], timeout: float = 900.0) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"{url} HTTP {exc.code}: {detail}") from exc


def judge_request(case: dict[str, Any], rubric: dict[str, Any], trial_dir: str) -> dict[str, Any]:
    return {
        "schema_version": "agenteval.judge_request.v1",
        "case": case,
        "rubric": rubric,
        "rubric_question": {},
        "agent_output": "",
        "trace_ref": {"scheme": "harbor", "trial_dir": trial_dir,
                      "trajectory_path": str(Path(trial_dir) / "agent" / "trajectory.json")},
        "artifact_ref": {"scheme": "harbor", "trial_dir": trial_dir,
                         "artifacts_root": str(Path(trial_dir) / "artifacts")},
        "metadata": {"protocol": "panel"},
    }


# --------------------------------------------------------------------------
# part 1: plan / router
# --------------------------------------------------------------------------

def plan_for_rubric(case_id: str, rubric: dict[str, Any], *,
                    deterministic_available: bool = True) -> dict[str, Any]:
    """Heuristic router: pick judge backends for one case+rubric.

    Deterministic first (free, stable), agent judge when artifacts need deep
    investigation, and a cheap per-question / joint LLM judge for breadth.
    Weighted aggregation happens in /v1/panel/evaluate. L6 will replace these
    weights with historical correctness signals from a gold dataset.
    """
    questions = rubric.get("questions") or []
    selected: list[dict[str, Any]] = []
    reasoning: list[str] = []
    if deterministic_available:
        selected.append({
            "skill_id": "deterministic", "role": "core", "weight": DEFAULT_WEIGHTS["deterministic"],
            "reason": "deterministic scorer is free and stable; anchors the panel",
        })
        reasoning.append("deterministic scorer available -> include as anchor")
    selected.append({
        "skill_id": "f_agent_pi_judge", "role": "core", "weight": DEFAULT_WEIGHTS["f_agent_pi_judge"],
        "reason": "artifacts need investigation (agent reads the real files)",
    })
    reasoning.append("artifacts/trajectory present -> agent judge investigates")
    if len(questions) > 3:
        selected.append({
            "skill_id": "single_rubric_judge", "role": "core", "weight": DEFAULT_WEIGHTS["single_rubric_judge"],
            "reason": "many questions -> per-question cheap judge keeps breadth",
        })
        reasoning.append(f"{len(questions)} questions -> per-question cheap judge")
    else:
        selected.append({
            "skill_id": "b_llm_judge", "role": "core", "weight": DEFAULT_WEIGHTS["b_llm_judge"],
            "reason": "few questions -> fast joint llm judge",
        })
        reasoning.append("few questions -> joint llm judge")
    return {
        "case_id": case_id,
        "selected_skills": selected,
        "skipped_skills": (),
        "routing_mode": "rule",
        "planner": {"backend": "panel", "version": "agent-eval.panel-router.v1"},
        "reasoning": reasoning,
    }


# --------------------------------------------------------------------------
# part 2: judge backends
# --------------------------------------------------------------------------

def run_backend(kind: str, request: dict[str, Any], *, scorer_path: str | None = None) -> dict[str, Any]:
    kind = (kind or "").strip().lower()
    if kind == "f":
        return _post(f"{JUDGE_URL}/v1/f-judge/evaluate", request)
    if kind == "b":
        return _post(f"{JUDGE_URL}/v1/judge/evaluate", request)
    if kind == "single":
        return _run_single(request)
    if kind == "deterministic":
        return _run_deterministic(request, scorer_path)
    raise ValueError(f"unknown judge backend {kind!r}")


def _run_single(request: dict[str, Any]) -> dict[str, Any]:
    """Per-question judge: one JudgeRequest per rubric question (legacy path)."""
    rubric = request.get("rubric") or {}
    questions = rubric.get("questions") or rubric.get("criteria") or []
    rows: list[dict[str, Any]] = []
    subscores: dict[str, float | None] = {}
    for q in questions:
        if not isinstance(q, dict):
            continue
        one = dict(request)
        one["rubric_question"] = dict(q)
        one["metadata"] = dict(request.get("metadata") or {})
        one["metadata"]["question_id"] = q.get("id")
        resp = _post(f"{JUDGE_URL}/v1/judge/evaluate", one, timeout=180.0)
        qid = str(q.get("id") or "")
        try:
            score = float(resp.get("score")) if resp.get("score") is not None else None
        except (TypeError, ValueError):
            score = None
        subscores[qid] = score
        rows.append({
            "question_id": qid,
            "score": score,
            "reason": str(resp.get("reasons") or {}).get(qid) or "",
            "status": resp.get("status"),
            "judge_backend": "single_rubric",
        })
    values = [v for v in subscores.values() if v is not None]
    overall = round(sum(values) / len(values), 4) if values else None
    status = "incomplete_evidence" if overall is None or any(r["status"] == "incomplete_evidence" for r in rows) else "scored"
    return {
        "schema_version": "agentjudge.joint_judgment.v1",
        "score": overall,
        "subscores": subscores,
        "question_judgments": rows,
        "provenance": {"protocol": "single_rubric_judge", "judge": "per-question llm"},
        "status": status,
    }


def _discover_scorer(trial_dir: str, request: dict[str, Any]) -> str | None:
    """Locate a deterministic scorer.py without the caller passing a path.

    artifact-repo projects Forge-generated scorers beside the Harbor task:
    ``jobs/<exp>/<job>/tasks/<task>/scorer.py``. Walk up from the trial dir
    and pick the first tasks/*/scorer.py. An explicit metadata.scorer_path
    wins when present.
    """
    explicit = (request.get("metadata") or {}).get("scorer_path")
    if explicit and Path(str(explicit)).is_file():
        return str(explicit)
    trial = Path(trial_dir)
    for parent in trial.parents:
        tasks = parent / "tasks"
        if tasks.is_dir():
            matches = sorted(tasks.glob("*/scorer.py"))
            if matches:
                return str(matches[0])
    return None


def _run_deterministic(request: dict[str, Any], scorer_path: str | None) -> dict[str, Any]:
    """Deterministic check: local scorer module if provided, else a stub rule.

    scorer_path points to a deterministic scorer.py (e.g. the Forge-generated
    scorer); it is imported and called with the frozen trial's artifacts.
    When no scorer can be found the backend reports incomplete_evidence
    (no fabricated numbers) rather than guessing.
    """
    trial_dir = None
    for ref in (request.get("trace_ref"), request.get("artifact_ref")):
        if isinstance(ref, dict) and ref.get("trial_dir"):
            trial_dir = str(ref["trial_dir"])
            break
    if not trial_dir:
        raise ValueError("deterministic judge requires trace_ref/artifact_ref.trial_dir")
    scorer_path = scorer_path or _discover_scorer(trial_dir, request)
    if not scorer_path or not Path(scorer_path).is_file():
        return {
            "schema_version": "agentjudge.joint_judgment.v1",
            "score": None,
            "subscores": {},
            "question_judgments": [],
            "provenance": {"protocol": "deterministic", "judge": "rule", "available": False,
                            "reason": "no scorer.py found near the trial"},
            "status": "incomplete_evidence",
        }
    import importlib.util
    spec = importlib.util.spec_from_file_location("panel_scorer", scorer_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, "_score_generic", None) or getattr(module, "score", None)
    artifacts_root = Path(trial_dir) / "artifacts" / "logs" / "artifacts"
    workspace = artifacts_root if artifacts_root.is_dir() else Path(trial_dir)
    if callable(getattr(module, "_score_generic", None)):
        rows = module._score_generic(attempt_id=Path(trial_dir).name, task={},
                                     workspace=str(workspace), artifact_dir=str(workspace), evidence=[])
    else:
        rows = fn(attempt_id=Path(trial_dir).name, task={}, workspace=str(workspace),
                  artifact_dir=str(workspace), evidence=[])
    subscores: dict[str, float | None] = {}
    reasons: dict[str, str] = {}
    judgments: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        qid = str(row.get("dimension_id") or row.get("dimension") or "")
        try:
            score = float(row.get("value")) / 100.0 if row.get("value") is not None else None
        except (TypeError, ValueError):
            score = None
        subscores[qid] = score
        reasons[qid] = str(row.get("detail") or "")
        judgments.append({"question_id": qid, "score": score, "reason": reasons[qid], "status": row.get("status")})
    values = [v for v in subscores.values() if v is not None]
    overall = round(sum(values) / len(values), 4) if values else None
    return {
        "schema_version": "agentjudge.joint_judgment.v1",
        "score": overall,
        "subscores": subscores,
        "reasons": reasons,
        "question_judgments": judgments,
        "provenance": {"protocol": "deterministic", "judge": "scorer", "scorer": scorer_path},
        "status": "scored" if overall is not None else "incomplete_evidence",
    }


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------

def aggregate(results: dict[str, dict[str, Any]], weights: dict[str, float]) -> dict[str, Any]:
    """Weighted fusion across judge backends (per rubric question)."""
    per_question: dict[str, list[tuple[float, float]]] = {}
    provenance: dict[str, Any] = {}
    for backend, resp in results.items():
        if not isinstance(resp, dict):
            continue
        provenance[backend] = {
            "protocol": (resp.get("provenance") or {}).get("protocol"),
            "score": resp.get("score"),
            "status": resp.get("status"),
        }
        w = weights.get(backend, 0.5)
        for qid, score in (resp.get("subscores") or {}).items():
            if score is not None:
                per_question.setdefault(str(qid), []).append((float(score), w))
    fused_scores: dict[str, float | None] = {}
    fused_reasons: dict[str, str] = {}
    for qid, entries in per_question.items():
        total_w = sum(w for _, w in entries)
        fused_scores[qid] = round(sum(s * w for s, w in entries) / total_w, 4) if total_w else None
    values = [v for v in fused_scores.values() if v is not None]
    overall = round(sum(values) / len(values), 4) if values else None
    return {
        "schema_version": "agentjudge.panel.v1",
        "score": overall,
        "subscores": fused_scores,
        "provenance": provenance,
        "judges": list(results.keys()),
        "status": "scored" if overall is not None else "incomplete_evidence",
    }
