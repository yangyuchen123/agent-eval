"""Runnable ASGI entry point for the standalone Agent Judge."""
from __future__ import annotations

import json
from typing import Any

from .http_service import JudgeHttpApplication, model_from_env
from .models import JudgeRequest


def create_app(*, model: Any | None = None, evidence_factory=None):
    try:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("install starlette and uvicorn to run agent-judge-server") from exc

    application: JudgeHttpApplication | None = None

    def get_application() -> JudgeHttpApplication:
        nonlocal application
        if application is None:
            application = JudgeHttpApplication(model or model_from_env(), evidence_factory=evidence_factory)
        return application

    async def evaluate(request: Request):
        if request.method != "POST":
            return JSONResponse({"error": "method_not_allowed"}, status_code=405)
        try:
            payload = await request.json()
            judge_request = JudgeRequest.model_validate(payload)
            result = await get_application().evaluate(judge_request)
            return JSONResponse(result)
        except ValueError as exc:
            return JSONResponse({"error": "invalid_request", "detail": str(exc)}, status_code=400)
        except Exception as exc:  # noqa: BLE001 - preserve HTTP boundary
            return JSONResponse({"error": "judge_error", "detail": repr(exc)}, status_code=500)

    async def health(request: Request):
        return JSONResponse({"status": "ok", "service": "agent-judge"})

    return Starlette(routes=[
        Route("/health", health, methods=["GET"]),
        Route("/v1/judge/evaluate", evaluate, methods=["POST"]),
    ])


app = create_app()


def main() -> None:
    import os
    import uvicorn
    # The Judge accepts local evidence references, so the safe default is
    # loopback-only. Deployments that intentionally expose it must opt in.
    uvicorn.run(
        "agentjudge.server:app",
        host=os.environ.get("JUDGE_HOST", "127.0.0.1"),
        port=int(os.environ.get("JUDGE_PORT", "8787")),
    )


if __name__ == "__main__":
    main()
