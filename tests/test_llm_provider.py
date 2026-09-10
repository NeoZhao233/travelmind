import json

import httpx
import pytest

from travelmind.agentic.llm_provider import (
    DeepSeekConfig,
    DeepSeekHTTPProvider,
    LLMOutputError,
)


def _response(content: str = '{"ok":true}') -> dict:
    return {
        "model": "deepseek-test",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }


def test_deepseek_provider_requests_json_mode_and_records_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["temperature"] == 0
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json=_response(), request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = DeepSeekHTTPProvider(DeepSeekConfig(api_key="test-key"), client=client)

    result = provider.complete_json(system_prompt="Return JSON", user_prompt="{}", max_tokens=20)

    assert result.data == {"ok": True}
    assert result.usage.total_tokens == 13
    assert result.provider_attempts == 1
    assert "test-key" not in repr(provider.config)


def test_deepseek_provider_retries_allowlisted_transient_status() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"error": "secret"}, request=request)
        return httpx.Response(200, json=_response(), request=request)

    provider = DeepSeekHTTPProvider(
        DeepSeekConfig(api_key="test-key", max_attempts=2),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )

    result = provider.complete_json(system_prompt="Return JSON", user_prompt="{}", max_tokens=20)

    assert result.provider_attempts == 2
    assert sleeps == [0.25]


@pytest.mark.parametrize("content", ["", "not-json", "[]"])
def test_deepseek_provider_rejects_unusable_json(content: str) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=_response(content), request=request)
    )
    provider = DeepSeekHTTPProvider(
        DeepSeekConfig(api_key="test-key"), client=httpx.Client(transport=transport)
    )

    with pytest.raises(LLMOutputError):
        provider.complete_json(system_prompt="Return JSON", user_prompt="{}", max_tokens=20)
