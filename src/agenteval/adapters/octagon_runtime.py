"""Small HTTP client for the AgentOctagon runtime API.

The client deliberately knows only the public ``POST /api/runs`` and
``GET /api/runs/{run_id}`` contract.  It does not import or start Octagon's
backend, preserving the runtime/evaluation/environment separation.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


class AgentOctagonRuntimeError(RuntimeError):
    """The AgentOctagon runtime rejected a request or became unreachable."""


@dataclass(frozen=True)
class OctagonRun:
    run_id: str
    status: str
    response: dict[str, Any]


class AgentOctagonRuntimeClient:
    """Synchronous, dependency-free client for a running Octagon server."""

    def __init__(self, base_url: str = "http://localhost:8100", *, request_timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.request_timeout = request_timeout

    def _request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(dict(payload)).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise AgentOctagonRuntimeError(
                f"AgentOctagon API {method} {path} returned HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise AgentOctagonRuntimeError(
                f"AgentOctagon API unavailable at {self.base_url}: {exc.reason}"
            ) from exc
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AgentOctagonRuntimeError(f"AgentOctagon API returned invalid JSON for {path}") from exc
        if not isinstance(value, dict):
            raise AgentOctagonRuntimeError(f"AgentOctagon API returned non-object JSON for {path}")
        return value

    def create_run(
        self,
        *,
        env_name: str,
        task_id: str,
        agents: list[str],
        model: str | None = None,
        models: dict[str, str] | None = None,
        compare_mode: str = "multi-agent",
        timeout_seconds: int | None = None,
        context: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> OctagonRun:
        if not env_name or "/" in env_name or "\\" in env_name:
            raise ValueError(f"invalid environment name: {env_name!r}")
        if not task_id:
            raise ValueError("task_id is required")
        if not agents:
            raise ValueError("at least one agent is required")
        payload: dict[str, Any] = {
            "env_name": env_name,
            "task_id": task_id,
            "agents": agents,
            "compare_mode": compare_mode,
        }
        if model:
            payload["model"] = model
        if models:
            payload["models"] = models
        if timeout_seconds is not None:
            payload["timeout_seconds"] = timeout_seconds
        if context:
            payload["context"] = context
        if constraints:
            payload["constraints"] = constraints
        response = self._request("POST", "/api/runs", payload)
        run_id = response.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise AgentOctagonRuntimeError(f"AgentOctagon create_run response has no run_id: {response!r}")
        return OctagonRun(run_id=run_id, status="created", response=response)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/runs/{run_id}")

    def wait_run(
        self,
        run_id: str,
        *,
        timeout: float = 3600.0,
        poll_interval: float = 5.0,
    ) -> OctagonRun:
        deadline = time.monotonic() + timeout
        terminal = {"completed", "failed", "cancelled", "canceled", "error"}
        last: dict[str, Any] = {}
        while True:
            last = self.get_run(run_id)
            status = str(last.get("status") or last.get("run_status") or "unknown").lower()
            if status in terminal:
                return OctagonRun(run_id=run_id, status=status, response=last)
            if time.monotonic() >= deadline:
                raise AgentOctagonRuntimeError(
                    f"timed out waiting for AgentOctagon run {run_id}; last status={status}"
                )
            time.sleep(max(0.0, poll_interval))

    def run(self, **kwargs: Any) -> OctagonRun:
        options = dict(kwargs)
        timeout = float(options.pop("wait_timeout", 3600.0))
        poll_interval = float(options.pop("poll_interval", 5.0))
        created = self.create_run(**options)
        return self.wait_run(created.run_id, timeout=timeout, poll_interval=poll_interval)
