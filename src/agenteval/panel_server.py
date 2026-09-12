"""HTTP entry for the judge panel (plan/router + judge backends + aggregation).

Endpoints:
  GET  /health
  POST /v1/plan                     # part 1 only: router decision, no scoring
  POST /v1/judge/{kind}             # part 2 only: one backend (f|b|single|deterministic)
  POST /v1/panel/evaluate           # full: plan -> selected backends -> weighted fusion
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any


def create_app() -> Any:
    try:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("install starlette and uvicorn to run the panel service") from exc

    from .panel_service import aggregate, judge_request, plan_for_rubric, run_backend

    async def body(request: Request) -> dict[str, Any]:
        return await request.json()

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "agent-judge-panel"})

    async def plan(request: Request) -> JSONResponse:
        try:
            payload = await body(request)
            case_id = str(payload.get("case_id") or payload.get("case", {}).get("case_id") or "")
            rubric = payload.get("rubric") or {}
            result = plan_for_rubric(
                case_id, rubric,
                deterministic_available=bool(payload.get("deterministic_available", True)),
            )
            return JSONResponse(result)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": "plan_error", "detail": repr(exc)}, status_code=500)

    async def judge(request: Request) -> JSONResponse:
        try:
            kind = request.path_params.get("kind", "")
            payload = await body(request)
            req = judge_request(payload.get("case") or {}, payload.get("rubric") or {},
                                str(payload.get("trial_dir") or ""))
            scorer = payload.get("scorer_path")
            result = await asyncio.to_thread(run_backend, kind, req, scorer_path=scorer)
            return JSONResponse(result)
        except ValueError as exc:
            return JSONResponse({"error": "invalid_request", "detail": str(exc)}, status_code=400)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": "judge_error", "detail": repr(exc)}, status_code=502)

    async def panel_evaluate(request: Request) -> JSONResponse:
        try:
            payload = await body(request)
            case = payload.get("case") or {}
            rubric = payload.get("rubric") or {}
            trial_dir = str(payload.get("trial_dir") or "")
            req = judge_request(case, rubric, trial_dir)
            requested = payload.get("backends") or []
            if requested:
                selected = [b for b in requested]
            else:
                plan = plan_for_rubric(str(case.get("case_id") or trial_dir), rubric,
                                       deterministic_available=bool(payload.get("deterministic_available", True)))
                selected = [s["skill_id"] for s in plan["selected_skills"]]
            scorer = payload.get("scorer_path")
            results: dict[str, dict[str, Any]] = {}
            skill_to_backend = {
                "deterministic": "deterministic",
                "f_agent_pi_judge": "f",
                "b_llm_judge": "b",
                "single_rubric_judge": "single",
            }
            for skill in selected:
                backend = skill_to_backend.get(skill, skill)
                try:
                    results[skill] = await asyncio.to_thread(run_backend, backend, req, scorer_path=scorer)
                except Exception as exc:  # noqa: BLE001 - one judge failing must not sink the panel
                    results[skill] = {
                        "schema_version": "agentjudge.joint_judgment.v1",
                        "score": None,
                        "subscores": {},
                        "question_judgments": [],
                        "provenance": {"protocol": backend, "error": repr(exc)},
                        "status": "judge_error",
                    }
            fused = aggregate(results, weights={s["skill_id"]: s.get("weight", 0.5) for s in plan_for_rubric(str(case.get("case_id") or trial_dir), rubric)["selected_skills"]})
            return JSONResponse({**fused, "judge_results": results})
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": "panel_error", "detail": repr(exc)}, status_code=500)

    return Starlette(routes=[
        Route("/health", health, methods=["GET"]),
        Route("/v1/plan", plan, methods=["POST"]),
        Route("/v1/judge/{kind}", judge, methods=["POST"]),
        Route("/v1/panel/evaluate", panel_evaluate, methods=["POST"]),
    ])


app = create_app()


def main() -> None:
    import uvicorn
    uvicorn.run(
        "agenteval.panel_server:app",
        host=os.environ.get("PANEL_HOST", "127.0.0.1"),
        port=int(os.environ.get("PANEL_PORT", "8788")),
    )


if __name__ == "__main__":
    main()
