"""PydanticAI execution backend for the RRD optimizer.

AgentOctagon is deliberately not used here as an agent runtime.  It remains a
producer/recorder of calibration responses.  This module owns only the LLM
calls needed by RRD and returns validated Pydantic models to the RRD adapter.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Literal, TypeVar

from .models import CalibrationResponse, Rubric

T = TypeVar("T")

# These imports are intentionally lazy: the base package's offline/unit-test
# installation need not import PydanticAI until this backend is selected.
def _pydantic_imports():
    try:
        from pydantic import BaseModel, ConfigDict, Field
        from pydantic_ai import Agent
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        from pydantic_ai.settings import ModelSettings
        try:
            import httpx2 as httpx
        except ImportError:
            import httpx
    except ImportError as exc:  # pragma: no cover - depends on optional runtime
        raise RuntimeError(
            "PydanticAI backend requires the 'rrd' extra: pip install 'agenteval[rrd]'"
        ) from exc
    return BaseModel, ConfigDict, Field, Agent, OpenAIChatModel, OpenAIProvider, ModelSettings, httpx


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


class PydanticAIBackend:
    """Typed, timeout-aware OpenAI-compatible backend used by RRD.

    The public ``infer`` method preserves the old callback contract, while the
    typed methods are used by the RRD phases.  Successful calls are cached by
    input digest; failed calls never enter the cache.
    """

    def __init__(self, *, base_url: str, model: str, api_key: str | None = None,
                 timeout: float = 600.0, retries: int = 1, temperature: float = 0.0,
                 max_tokens: int = 8192, cache_path: str | Path | None = None,
                 call_log_path: str | Path | None = None, response_batch_size: int = 5,
                 thinking: bool = False, extra_body: dict[str, Any] | None = None):
        if not base_url or not model:
            raise ValueError("base_url and model are required")
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self.api_key = api_key or os.getenv("GENERATOR_API_KEY") or os.getenv("JUDGE_API_KEY") or os.getenv("OPENAI_API_KEY") or "api-key-not-set"
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.cache_path = Path(cache_path) if cache_path else None
        self.call_log_path = Path(call_log_path) if call_log_path else None
        self.response_batch_size = max(1, int(response_batch_size))
        self.thinking = bool(thinking)
        self.extra_body = dict(extra_body or {})
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._load_cache()

    @property
    def config_digest(self) -> str:
        return _digest({"base_url": self.base_url, "model": self.model_name,
                        "timeout": self.timeout, "retries": self.retries,
                        "temperature": self.temperature, "max_tokens": self.max_tokens,
                        "response_batch_size": self.response_batch_size,
                        "thinking": self.thinking, "extra_body": self.extra_body})

    def _load_cache(self) -> None:
        if not self.cache_path or not self.cache_path.exists():
            return
        for line in self.cache_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                if item.get("status") == "success" and item.get("cache_key"):
                    self._cache[item["cache_key"]] = item["parsed"]
            except (ValueError, TypeError):
                continue

    def _record(self, item: dict[str, Any]) -> None:
        if self.call_log_path:
            self.call_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self.call_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    def _make_agent(self, output_type: type[Any], system_prompt: str):
        BaseModel, ConfigDict, Field, Agent, OpenAIChatModel, OpenAIProvider, ModelSettings, httpx = _pydantic_imports()
        # Explicit connect/read/write/pool values make long internal endpoint
        # calls observable and avoid urllib's single opaque timeout.
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout=self.timeout, connect=min(self.timeout, 30.0)),
            follow_redirects=True,
        )
        provider = OpenAIProvider(base_url=self.base_url, api_key=self.api_key, http_client=http_client)
        settings: dict[str, Any] = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "thinking": self.thinking,
            "openai_reasoning_effort": "none" if not self.thinking else None,
            "extra_body": {
                "reasoning": {"effort": "none", "exclude": True},
                **self.extra_body,
            } if not self.thinking else self.extra_body,
        }
        settings = {k: v for k, v in settings.items() if v is not None}
        model = OpenAIChatModel(self.model_name, provider=provider, settings=ModelSettings(**settings))
        return Agent(model=model, output_type=output_type, system_prompt=system_prompt,
                     retries=self.retries, name="rrd-typed-agent"), http_client

    async def _run_async(self, *, messages: list[dict[str, Any]], output_type: type[Any],
                         phase: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        system = "\n".join(str(x.get("content", "")) for x in messages if x.get("role") == "system")
        user = "\n\n".join(str(x.get("content", "")) for x in messages if x.get("role") != "system")
        key = _digest({"phase": phase, "model": self.model_name, "config": self.config_digest,
                       "system": system, "user": user, "output_type": output_type.__name__})
        if key in self._cache:
            return {"parsed": self._cache[key], "response_metadata": {"cache_hit": True, "cache_key": key}, "raw_output_text": ""}
        started = time.monotonic()
        last_exc: BaseException | None = None
        # Transport retries are independent of Agent.retries so a 502 does not
        # invalidate the input digest / cache key.
        attempts = 4
        for attempt in range(1, attempts + 1):
            agent, http_client = self._make_agent(output_type, system)
            try:
                result = await agent.run(user)
                output = result.output
                parsed = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
                if not isinstance(parsed, dict):
                    raise ValueError("PydanticAI output must serialize to an object")
                self._cache[key] = parsed
                if self.cache_path:
                    self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                    with self._lock, self.cache_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps({"cache_key": key, "status": "success", "parsed": parsed}, ensure_ascii=False) + "\n")
                usage = None
                try:
                    usage_obj = result.usage()
                    usage = usage_obj.model_dump(mode="json") if hasattr(usage_obj, "model_dump") else str(usage_obj)
                except Exception:
                    pass
                self._record({"call_id": _digest({key, time.time_ns()}), "phase": phase,
                              "input_digest": key, "status": "success",
                              "elapsed_seconds": round(time.monotonic() - started, 3),
                              "model": self.model_name, "cache_key": key,
                              "raw_output_available": False, "usage": usage, "attempt": attempt,
                              **(metadata or {})})
                return {"parsed": parsed, "response_metadata": {"cache_hit": False, "cache_key": key, "usage": usage, "attempt": attempt}, "raw_output_text": ""}
            except Exception as exc:
                last_exc = exc
                retryable = "502" in repr(exc) or "overloaded" in repr(exc).lower() or "timeout" in repr(exc).lower() or "503" in repr(exc)
                self._record({"call_id": _digest({key, time.time_ns()}), "phase": phase,
                              "input_digest": key, "status": "error",
                              "elapsed_seconds": round(time.monotonic() - started, 3),
                              "model": self.model_name, "cache_key": key,
                              "raw_output_available": False, "error": repr(exc), "attempt": attempt,
                              "retryable": retryable, **(metadata or {})})
                if not retryable or attempt >= attempts:
                    raise
                await asyncio.sleep(min(8.0, 1.5 * attempt))
            finally:
                await http_client.aclose()
        raise last_exc if last_exc else RuntimeError("RRD backend failed without exception")

    def _run(self, **kwargs: Any) -> dict[str, Any]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._run_async(**kwargs))
        # Existing RRD callbacks are synchronous. If called from an async host,
        # isolate the event loop in a short-lived worker thread instead of
        # nesting asyncio.run() into the host loop.
        result: list[dict[str, Any]] = []
        error: list[BaseException] = []
        def worker() -> None:
            try: result.append(asyncio.run(self._run_async(**kwargs)))
            except BaseException as exc: error.append(exc)
        thread = threading.Thread(target=worker, daemon=True)
        thread.start(); thread.join()
        if error: raise error[0]
        return result[0]

    def infer(self, messages: list[dict[str, Any]], *, output_type: type[Any] | None = None,
              phase: str = "generic", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if output_type is None:
            BaseModel, ConfigDict, Field, *_ = _pydantic_imports()
            class GenericObject(BaseModel):
                model_config = ConfigDict(extra="allow")
            output_type = GenericObject
        return self._run(messages=messages, output_type=output_type, phase=phase, metadata=metadata)

    def evaluate_matrix(self, task: str, rubrics: list[Rubric], responses: list[CalibrationResponse],
                        prompt_builder) -> tuple[dict[str, dict[str, int]], dict[str, Any]]:
        _pydantic_imports()
        from .typed_outputs import MatrixOutput
        # Batch by responses to keep schema output bounded; merge into one matrix.
        merged = {r.rubric_id: {} for r in rubrics}
        metas = []
        for offset in range(0, len(responses), self.response_batch_size):
            batch = responses[offset:offset + self.response_batch_size]
            result = self.infer(prompt_builder(task, rubrics, batch), output_type=MatrixOutput,
                                phase="evaluation", metadata={"rubric_ids": [r.rubric_id for r in rubrics], "response_ids": [x.response_id for x in batch]})
            parsed = result["parsed"]
            for rid, row in parsed["matrix"].items():
                if rid in merged:
                    merged[rid].update({str(k): int(v) for k, v in row.items()})
            metas.append(result.get("response_metadata"))
        for rid in merged:
            missing = [x.response_id for x in responses if x.response_id not in merged[rid]]
            if missing:
                raise ValueError(f"PydanticAI matrix missing {rid}: {missing}")
        return merged, {"backend": "pydantic_ai", "calls": len(metas), "calls_metadata": metas}

    def decompose(self, messages: list[dict[str, Any]], output_type: type[Any], metadata=None):
        return self.infer(messages, output_type=output_type, phase="decomposition", metadata=metadata)
