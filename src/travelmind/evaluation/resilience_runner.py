from __future__ import annotations

import hashlib

from travelmind.retrieval.resilience import (
    CircuitBreaker,
    InMemoryRetrievalCache,
    ResilientRetriever,
    RetrievalResiliencePolicy,
    RetrievalUnavailableError,
)
from travelmind.schemas import Evidence


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _MutableRetriever:
    def __init__(self, evidence: list[Evidence]) -> None:
        self.evidence = evidence
        self.available = True
        self.calls = 0

    def search(self, queries: list[str], *, limit: int) -> list[Evidence]:
        del queries
        self.calls += 1
        if not self.available:
            raise TimeoutError("provider payload must not escape")
        return self.evidence[:limit]


def _evidence(freshness: str) -> Evidence:
    return Evidence(
        id=f"{freshness}-evidence",
        content="controlled evidence",
        source_url="https://example.invalid/resilience",
        source_type="official",
        score=1,
        metadata={"freshness": freshness},
    )


def _stack(clock: _Clock, freshness: str):
    primary = _MutableRetriever([_evidence(freshness)])
    breaker = CircuitBreaker(
        failure_threshold=1,
        recovery_timeout_seconds=30,
        clock=clock,
    )
    resilient = ResilientRetriever(
        primary,
        breaker=breaker,
        cache=InMemoryRetrievalCache(clock=clock),
        policy=RetrievalResiliencePolicy(
            fresh_ttl_seconds=10,
            maximum_stale_seconds=30,
        ),
    )
    return primary, breaker, resilient


def run_retrieval_resilience_drill() -> dict:
    dynamic_clock = _Clock()
    dynamic_primary, dynamic_breaker, dynamic = _stack(dynamic_clock, "dynamic")
    warm = dynamic.search_with_diagnostics(["dynamic query"], limit=3)
    dynamic_primary.available = False
    first_failure = dynamic.search_with_diagnostics(["dynamic query"], limit=3)
    state_after_failure = dynamic_breaker.snapshot().state
    calls_after_open = dynamic_primary.calls
    fast_fail = dynamic.search_with_diagnostics(["dynamic query"], limit=3)
    fast_fail_avoided_call = dynamic_primary.calls == calls_after_open
    dynamic_clock.advance(11)
    try:
        dynamic.search_with_diagnostics(["dynamic query"], limit=3)
        dynamic_stale_rejected = False
        dynamic_error_type = None
    except RetrievalUnavailableError as exc:
        dynamic_stale_rejected = True
        dynamic_error_type = type(exc).__name__
    dynamic_clock.advance(19)
    dynamic_primary.available = True
    recovered = dynamic.search_with_diagnostics(["dynamic query"], limit=3)
    recovered_state = dynamic_breaker.snapshot().state

    static_clock = _Clock()
    static_primary, _, static = _stack(static_clock, "static")
    static.search_with_diagnostics(["static query"], limit=3)
    static_clock.advance(20)
    static_primary.available = False
    stale_static = static.search_with_diagnostics(["static query"], limit=3)
    static_clock.advance(11)
    try:
        static.search_with_diagnostics(["static query"], limit=3)
        expired_static_rejected = False
    except RetrievalUnavailableError:
        expired_static_rejected = True

    checks = {
        "healthy_primary_cached": warm.mode == "primary",
        "first_transient_failure_uses_fresh_cache": (
            first_failure.mode == "cache_fresh" and state_after_failure == "open"
        ),
        "open_circuit_avoids_provider_call": (
            fast_fail.mode == "cache_fresh" and fast_fail_avoided_call
        ),
        "stale_dynamic_fails_closed": dynamic_stale_rejected,
        "half_open_probe_recovers": (recovered.mode == "primary" and recovered_state == "closed"),
        "bounded_stale_static_is_allowed": stale_static.mode == "cache_stale",
        "expired_static_fails_closed": expired_static_rejected,
        "exception_payload_redacted": dynamic_error_type == "RetrievalUnavailableError",
    }
    return {
        "experiment": "stage7b-circuit-breaker-and-cache-freshness-drill",
        "configuration_sha256": hashlib.sha256(
            b"circuit-v1|threshold=1|recovery=30|fresh=10|max-stale=30"
        ).hexdigest(),
        "configuration": {
            "failure_threshold": 1,
            "recovery_timeout_seconds": 30,
            "fresh_ttl_seconds": 10,
            "maximum_stale_seconds": 30,
            "stale_allowed_freshness_classes": ["static"],
        },
        "checks": checks,
        "metrics": {
            "check_pass_rate": sum(checks.values()) / len(checks),
            "fast_fail_provider_call_avoidance": float(fast_fail_avoided_call),
            "dynamic_stale_rejection_rate": float(dynamic_stale_rejected),
            "half_open_recovery_rate": float(
                recovered.mode == "primary" and recovered_state == "closed"
            ),
            "bounded_static_stale_availability_rate": float(stale_static.mode == "cache_stale"),
        },
        "limitations": [
            "Timeouts are injected; provider-native connection/read deadlines remain required.",
            "The cache is process-local and does not test Redis consistency or eviction.",
            "Only static evidence is stale-eligible; fact-level policy needs live adapters.",
        ],
    }
