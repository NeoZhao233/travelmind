from datetime import UTC, datetime, timedelta

import httpx
import pytest

from travelmind.ingestion import (
    CachedSource,
    ConditionalSourceFetcher,
    FetchResponse,
    SourceFetchPolicy,
    SourcePolicyError,
    SourceResponseRejectedError,
    SourceUnavailableError,
)

NOW = datetime(2026, 9, 9, tzinfo=UTC)
URL = "https://official.example/place"


class ScriptedTransport:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _policy(freshness_class="dynamic", **updates):
    values = {
        "allowed_hosts": frozenset({"official.example"}),
        "freshness_class": freshness_class,
        "fresh_ttl_seconds": 10,
        "maximum_stale_seconds": 30,
        "maximum_attempts": 3,
        "backoff_base_seconds": 0.1,
        "backoff_cap_seconds": 0.25,
    }
    values.update(updates)
    return SourceFetchPolicy(**values)


def _cached(age_seconds, *, etag='"v1"'):
    observed = NOW - timedelta(seconds=age_seconds)
    return CachedSource(
        url=URL,
        content=b"cached",
        content_type="application/json",
        captured_at=observed,
        validated_at=observed,
        etag=etag,
        last_modified="Wed, 09 Sep 2026 00:00:00 GMT",
    )


def test_conditional_304_refreshes_validation_time_without_new_content() -> None:
    transport = ScriptedTransport([FetchResponse(304, {"etag": '"v1"'}, b"")])
    fetcher = ConditionalSourceFetcher(transport, _policy(), now=lambda: NOW)

    result = fetcher.fetch(URL, _cached(20))

    assert result.diagnostics.mode == "not_modified"
    assert result.source.content == b"cached"
    assert result.source.validated_at == NOW
    assert transport.requests[0].headers["if-none-match"] == '"v1"'
    assert "if-modified-since" in transport.requests[0].headers


def test_transient_failures_retry_with_bounded_backoff_then_succeed() -> None:
    sleeps = []
    transport = ScriptedTransport(
        [
            TimeoutError("secret one"),
            FetchResponse(503, {"retry-after": "99"}, b"secret two"),
            FetchResponse(200, {"content-type": "application/json"}, b"{}"),
        ]
    )
    fetcher = ConditionalSourceFetcher(
        transport,
        _policy(),
        now=lambda: NOW,
        sleeper=sleeps.append,
    )

    result = fetcher.fetch(URL)

    assert result.diagnostics.mode == "network_200"
    assert result.diagnostics.attempts == 3
    assert sleeps == [0.1, 0.25]


def test_httpx_transport_errors_use_the_same_bounded_fallback_policy() -> None:
    request = httpx.Request("GET", URL)
    transport = ScriptedTransport(
        [httpx.ConnectTimeout("sensitive transport detail", request=request)] * 3
    )
    fetcher = ConditionalSourceFetcher(transport, _policy(), now=lambda: NOW)

    result = fetcher.fetch(URL, _cached(1))

    assert result.diagnostics.mode == "cache_fresh"
    assert result.diagnostics.attempts == 3
    assert result.diagnostics.error_type == "ConnectTimeout"


def test_dynamic_stale_cache_fails_closed_but_static_cache_is_bounded() -> None:
    dynamic = ConditionalSourceFetcher(
        ScriptedTransport([TimeoutError()] * 3), _policy("dynamic"), now=lambda: NOW
    )
    with pytest.raises(SourceUnavailableError, match="no admissible cache"):
        dynamic.fetch(URL, _cached(20))

    static = ConditionalSourceFetcher(
        ScriptedTransport([TimeoutError()] * 3), _policy("static"), now=lambda: NOW
    )
    result = static.fetch(URL, _cached(20))
    assert result.diagnostics.mode == "cache_stale"
    assert result.diagnostics.error_type == "TimeoutError"

    expired = ConditionalSourceFetcher(
        ScriptedTransport([TimeoutError()] * 3), _policy("static"), now=lambda: NOW
    )
    with pytest.raises(SourceUnavailableError):
        expired.fetch(URL, _cached(31))


def test_non_retryable_response_and_unsafe_url_are_rejected_immediately() -> None:
    transport = ScriptedTransport(
        [FetchResponse(401, {"content-type": "application/json"}, b"secret")]
    )
    fetcher = ConditionalSourceFetcher(transport, _policy(), now=lambda: NOW)
    with pytest.raises(SourceResponseRejectedError, match="401"):
        fetcher.fetch(URL, _cached(1))
    assert len(transport.requests) == 1

    for unsafe in (
        "http://official.example/place",
        "https://evil.example/place",
        "https://user:password@official.example/place",
        "https://official.example:8443/place",
        "https://official.example:not-a-port/place",
    ):
        with pytest.raises(SourcePolicyError):
            fetcher.fetch(unsafe)


def test_response_size_content_type_and_orphan_304_fail_closed() -> None:
    oversized = ConditionalSourceFetcher(
        ScriptedTransport([FetchResponse(200, {"content-type": "application/json"}, b"12345")]),
        _policy(maximum_response_bytes=4),
        now=lambda: NOW,
    )
    with pytest.raises(SourceResponseRejectedError, match="size"):
        oversized.fetch(URL)

    binary = ConditionalSourceFetcher(
        ScriptedTransport(
            [FetchResponse(200, {"content-type": "application/octet-stream"}, b"ok")]
        ),
        _policy(),
        now=lambda: NOW,
    )
    with pytest.raises(SourceResponseRejectedError, match="content type"):
        binary.fetch(URL)

    orphan = ConditionalSourceFetcher(
        ScriptedTransport([FetchResponse(304, {}, b"")]), _policy(), now=lambda: NOW
    )
    with pytest.raises(SourceResponseRejectedError, match="without a cached"):
        orphan.fetch(URL)
