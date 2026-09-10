from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from travelmind.ingestion import (
    CachedSource,
    ConditionalSourceFetcher,
    FetchResponse,
    SourceFetchPolicy,
    SourcePolicyError,
    SourceUnavailableError,
)

_NOW = datetime(2026, 9, 9, tzinfo=UTC)
_URL = "https://official.example/place"


class _ScriptedTransport:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes.copy()
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _policy(freshness_class: str) -> SourceFetchPolicy:
    return SourceFetchPolicy(
        allowed_hosts=frozenset({"official.example"}),
        freshness_class=freshness_class,
        fresh_ttl_seconds=10,
        maximum_stale_seconds=30,
        maximum_attempts=3,
        backoff_base_seconds=0.1,
        backoff_cap_seconds=0.25,
    )


def _cached(age: float) -> CachedSource:
    observed = _NOW - timedelta(seconds=age)
    return CachedSource(
        url=_URL,
        content=b"cached official content",
        content_type="application/json",
        captured_at=observed,
        validated_at=observed,
        etag='"v1"',
        last_modified="Wed, 09 Sep 2026 00:00:00 GMT",
    )


def _fetcher(transport, freshness_class: str, sleeps: list[float] | None = None):
    return ConditionalSourceFetcher(
        transport,
        _policy(freshness_class),
        now=lambda: _NOW,
        sleeper=(sleeps.append if sleeps is not None else lambda seconds: None),
    )


def run_source_fetch_drill() -> dict:
    initial_transport = _ScriptedTransport(
        [
            FetchResponse(
                200,
                {
                    "content-type": "application/json",
                    "etag": '"v2"',
                    "last-modified": "Wed, 09 Sep 2026 01:00:00 GMT",
                },
                b'{"status":"open"}',
            )
        ]
    )
    initial = _fetcher(initial_transport, "dynamic").fetch(_URL)

    conditional_transport = _ScriptedTransport([FetchResponse(304, {}, b"")])
    conditional = _fetcher(conditional_transport, "dynamic").fetch(_URL, initial.source)

    sleeps: list[float] = []
    recovered_transport = _ScriptedTransport(
        [
            TimeoutError("sensitive timeout payload"),
            FetchResponse(503, {"retry-after": "99"}, b"sensitive response"),
            FetchResponse(200, {"content-type": "application/json"}, b"{}"),
        ]
    )
    recovered = _fetcher(recovered_transport, "dynamic", sleeps).fetch(_URL)

    try:
        _fetcher(_ScriptedTransport([TimeoutError("secret")] * 3), "dynamic").fetch(
            _URL, _cached(20)
        )
        dynamic_stale_rejected = False
    except SourceUnavailableError:
        dynamic_stale_rejected = True

    static = _fetcher(_ScriptedTransport([TimeoutError("secret")] * 3), "static").fetch(
        _URL, _cached(20)
    )

    unsafe_transport = _ScriptedTransport([])
    try:
        _fetcher(unsafe_transport, "dynamic").fetch("http://127.0.0.1/admin")
        unsafe_url_rejected = False
    except SourcePolicyError:
        unsafe_url_rejected = True

    serialized = repr(
        [
            initial.diagnostics,
            conditional.diagnostics,
            recovered.diagnostics,
            static.diagnostics,
        ]
    )
    checks = {
        "network_response_accepted": initial.diagnostics.mode == "network_200",
        "conditional_headers_sent": (
            conditional_transport.requests[0].headers.get("if-none-match") == '"v2"'
            and "if-modified-since" in conditional_transport.requests[0].headers
        ),
        "not_modified_refreshed_validation": (
            conditional.diagnostics.mode == "not_modified"
            and conditional.source.content == initial.source.content
            and conditional.source.validated_at == _NOW
        ),
        "transient_retry_recovered": (
            recovered.diagnostics.mode == "network_200"
            and recovered.diagnostics.attempts == 3
            and sleeps == [0.1, 0.25]
        ),
        "dynamic_stale_failed_closed": dynamic_stale_rejected,
        "bounded_static_stale_allowed": static.diagnostics.mode == "cache_stale",
        "unsafe_url_blocked_before_transport": (
            unsafe_url_rejected and not unsafe_transport.requests
        ),
        "failure_payload_redacted": "sensitive" not in serialized and "secret" not in serialized,
    }
    return {
        "experiment": "stage8b-conditional-fetch-and-freshness-drill",
        "configuration_sha256": hashlib.sha256(
            b"https-host-policy|conditional-get|retry-3|fresh-10|stale-30"
        ).hexdigest(),
        "checks": checks,
        "metrics": {
            "check_pass_rate": sum(checks.values()) / len(checks),
            "conditional_revalidation_rate": float(checks["not_modified_refreshed_validation"]),
            "transient_recovery_rate": float(checks["transient_retry_recovered"]),
            "dynamic_stale_rejection_rate": float(checks["dynamic_stale_failed_closed"]),
            "bounded_static_availability_rate": float(checks["bounded_static_stale_allowed"]),
            "unsafe_transport_call_rate": float(bool(unsafe_transport.requests)),
        },
        "limitations": [
            "The drill uses an injected transport and does not contact a live source.",
            "Hostname allowlisting does not by itself prevent DNS rebinding to private addresses.",
            "The synchronous adapter checks size after download; production should stream "
            "with a cap.",
            "Retry-After currently supports bounded numeric seconds, not HTTP-date values.",
        ],
    }
