from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field


class LLMProviderError(RuntimeError):
    """A sanitized external-provider failure."""


class LLMOutputError(RuntimeError):
    """The provider returned no usable structured output."""


class LLMUsage(BaseModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class StructuredLLMResult(BaseModel):
    data: dict[str, Any]
    model: str
    finish_reason: str | None = None
    usage: LLMUsage = Field(default_factory=LLMUsage)
    latency_ms: float = Field(ge=0)
    provider_attempts: int = Field(ge=1)


class StructuredLLMProvider(Protocol):
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> StructuredLLMResult: ...


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str = field(repr=False)
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    timeout_seconds: float = 20.0
    max_attempts: int = 2
    backoff_seconds: float = 0.25

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("DeepSeek API key must not be empty")
        if self.timeout_seconds <= 0 or self.max_attempts < 1 or self.backoff_seconds < 0:
            raise ValueError("Invalid DeepSeek timeout, retry, or backoff configuration")


class DeepSeekHTTPProvider:
    """Minimal JSON-mode DeepSeek adapter with bounded transient retries."""

    _RETRYABLE_STATUS = {429, 500, 503}

    def __init__(
        self,
        config: DeepSeekConfig,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=config.timeout_seconds)
        self._sleep = sleep

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> StructuredLLMResult:
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        started = perf_counter()
        response: httpx.Response | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                response = self._client.post(
                    f"{self.config.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self.config.api_key}"},
                    json={
                        "model": self.config.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "response_format": {"type": "json_object"},
                        "thinking": {"type": "disabled"},
                        "max_tokens": max_tokens,
                        "temperature": 0,
                        "stream": False,
                    },
                )
            except httpx.TimeoutException as exc:
                if attempt < self.config.max_attempts:
                    self._sleep(self.config.backoff_seconds * attempt)
                    continue
                raise LLMProviderError("DeepSeek request timed out") from exc
            except httpx.HTTPError as exc:
                raise LLMProviderError("DeepSeek transport failed") from exc
            should_retry = (
                response.status_code in self._RETRYABLE_STATUS
                and attempt < self.config.max_attempts
            )
            if should_retry:
                self._sleep(self.config.backoff_seconds * attempt)
                continue
            if response.status_code >= 400:
                raise LLMProviderError(f"DeepSeek HTTP status {response.status_code}")
            break

        assert response is not None
        try:
            payload = response.json()
            choice = payload["choices"][0]
            content = choice["message"]["content"]
            finish_reason = choice.get("finish_reason")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMOutputError("DeepSeek response envelope is invalid") from exc
        if finish_reason == "length":
            raise LLMOutputError("DeepSeek JSON output was truncated")
        if not isinstance(content, str) or not content.strip():
            raise LLMOutputError("DeepSeek returned empty JSON content")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMOutputError("DeepSeek returned invalid JSON content") from exc
        if not isinstance(data, dict):
            raise LLMOutputError("DeepSeek JSON output must be an object")
        usage = payload.get("usage") or {}
        return StructuredLLMResult(
            data=data,
            model=str(payload.get("model", self.config.model)),
            finish_reason=finish_reason,
            usage=LLMUsage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            ),
            latency_ms=(perf_counter() - started) * 1000,
            provider_attempts=attempt,
        )
