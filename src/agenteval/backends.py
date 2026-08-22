"""OpenAI-compatible LLM backend (urllib only, no SDK dependency).

Adapted from HarnessEval-W's skill backend (Apache-2.0): same retry /
wire-API fallback strategy, trimmed to what the framework needs.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

from .io import value_digest

RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
WIRE_APIS = {"responses", "response", "chat", "chat_completions", "chat/completions"}


@dataclass
class LLMBackend:
    """Speaks the OpenAI wire protocol (chat/completions or responses)."""

    base_url: str
    model: str
    api_key: str | None = None
    wire_api: str = "chat"
    temperature: float = 0.0
    max_tokens: int = 2048
    timeout: float = 90.0
    retries: int = 1
    json_mode: bool = True

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if not self.base_url or not self.model:
            raise ValueError("base_url and model are required")
        if self.wire_api not in WIRE_APIS:
            raise ValueError(f"unsupported wire API: {self.wire_api}")

    @property
    def config_digest(self) -> str:
        return value_digest({
            "base_url": self.base_url, "model": self.model,
            "wire_api": self.wire_api, "temperature": self.temperature,
            "max_tokens": self.max_tokens, "json_mode": self.json_mode,
        })

    # ------------------------------------------------------- wire --------

    def _targets_and_body(self, messages: list[dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
        if self.wire_api in {"responses", "response"}:
            urls = [self.base_url] if self.base_url.endswith("/responses") else [
                f"{self.base_url}/responses", f"{self.base_url}/v1/responses"]
            body: dict[str, Any] = {
                "model": self.model, "input": messages, "temperature": self.temperature,
                "max_output_tokens": self.max_tokens,
            }
            if self.json_mode:
                body["text"] = {"format": {"type": "json_object"}}
        else:
            urls = [self.base_url] if self.base_url.endswith("/chat/completions") else [
                f"{self.base_url}/chat/completions", f"{self.base_url}/v1/chat/completions"]
            body = {
                "model": self.model, "messages": messages,
                "temperature": self.temperature, "max_tokens": self.max_tokens,
            }
            if self.json_mode:
                body["response_format"] = {"type": "json_object"}
        return urls, body

    def _post(self, url: str, body: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:  # noqa: S310
                status = int(resp.status)
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            raw = exc.read().decode("utf-8", errors="replace")
        value = json.loads(raw) if raw.strip() else {}
        return status, value if isinstance(value, dict) else {"response": value}

    # ----------------------------------------------------- infer --------

    def infer(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Call the model; returns parsed dict + full provenance."""
        urls, body = self._targets_and_body(messages)
        started = time.monotonic()
        attempts: list[dict[str, Any]] = []
        response, request_url, last_error = None, None, None

        for url in urls:
            for attempt in range(1, max(1, self.retries + 1) + 1):
                try:
                    status, data = self._post(url, body)
                    error = None
                except (TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
                    status, data, error = None, {}, repr(exc)
                attempts.append({
                    "attempt": attempt, "url": url, "status_code": status,
                    "error": error,
                    "elapsed_seconds": round(time.monotonic() - started, 6),
                })
                if status is not None and status < 400:
                    response, request_url = data, url
                    break
                last_error = error or json.dumps(data, ensure_ascii=False)[:1000]
                if status is not None and status not in RETRYABLE_STATUS_CODES:
                    break
                if attempt <= self.retries:
                    time.sleep(min(0.5 * (2 ** (attempt - 1)), 8.0)
                               + random.uniform(0.0, 0.25))
            if response is not None:
                break
            if attempts and attempts[-1]["status_code"] not in {404, 405}:
                break

        if response is None:
            raise RuntimeError(f"LLM request failed: {last_error}")

        raw_text = _response_text(response)
        return {
            "parsed": _parse_json(raw_text) if self.json_mode else {"text": raw_text},
            "raw_output_text": raw_text,
            "response_metadata": {
                "id": response.get("id"), "model": response.get("model"),
                "usage": response.get("usage"), "request_url": request_url,
                "elapsed_seconds": round(time.monotonic() - started, 6),
                "attempts": attempts,
            },
        }


# --------------------------------------------------------- helpers -------

def _response_text(response: Mapping[str, Any]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    choices = response.get("choices") or []
    if choices and isinstance(choices[0], Mapping):
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content
    parts: list[str] = []
    for output in response.get("output") or []:
        if isinstance(output, Mapping):
            for item in output.get("content") or []:
                if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
    text = "\n".join(parts).strip()
    if not text:
        raise RuntimeError("LLM response contains no output text")
    return text


def _parse_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        if stripped.endswith("```"):
            stripped = stripped[:-3].rstrip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        if start < 0:
            raise RuntimeError("LLM response is not a JSON object") from None
        try:
            value, _ = json.JSONDecoder().raw_decode(stripped[start:])
        except json.JSONDecodeError as exc:
            raise RuntimeError("LLM response is not a JSON object") from exc
    if not isinstance(value, dict):
        raise RuntimeError("LLM response JSON must be an object")
    return value


def build_messages(system: str, user: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]
