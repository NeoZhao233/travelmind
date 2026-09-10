from pathlib import Path

import pytest

from travelmind.evaluation.observability_runner import _input
from travelmind.observability import InMemoryTelemetrySink
from travelmind.pipeline import EndToEndPlanningPipeline
from travelmind.planner.llm_candidates import DeterministicPlanningStrategy
from travelmind.retrieval.bm25 import BM25Retriever
from travelmind.retrieval.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    InMemoryRetrievalCache,
    ResilientRetriever,
    RetrievalResiliencePolicy,
    RetrievalUnavailableError,
)
from travelmind.schemas import Evidence

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _evidence(freshness: str) -> Evidence:
    return Evidence(
        id="evidence-1",
        content="grounded",
        source_url="https://example.invalid",
        source_type="official",
        score=1,
        metadata={"freshness": freshness},
    )


class ScriptedRetriever:
    def __init__(self, outcomes) -> None:
        self.outcomes = iter(outcomes)
        self.calls = 0

    def search(self, queries: list[str], *, limit: int) -> list[Evidence]:
        del queries, limit
        self.calls += 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_circuit_opens_fast_and_recovers_through_one_half_open_probe() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_seconds=10,
        clock=clock,
    )
    calls = 0

    def fail() -> list[Evidence]:
        nonlocal calls
        calls += 1
        raise TimeoutError("secret provider detail")

    for _ in range(2):
        with pytest.raises(TimeoutError):
            breaker.call(fail)
    assert breaker.snapshot().state == "open"
    with pytest.raises(CircuitOpenError):
        breaker.call(fail)
    assert calls == 2

    clock.advance(10)
    assert breaker.call(lambda: [_evidence("static")])
    assert breaker.snapshot().state == "closed"
    assert breaker.snapshot().consecutive_failures == 0


def _resilient(
    clock: FakeClock,
    outcomes,
    *,
    policy: RetrievalResiliencePolicy | None = None,
) -> ResilientRetriever:
    return ResilientRetriever(
        ScriptedRetriever(outcomes),
        breaker=CircuitBreaker(
            failure_threshold=1,
            recovery_timeout_seconds=30,
            clock=clock,
        ),
        cache=InMemoryRetrievalCache(clock=clock),
        policy=policy,
    )


def test_fresh_cache_can_cover_a_transient_dynamic_retrieval_failure() -> None:
    clock = FakeClock()
    retriever = _resilient(
        clock,
        [[_evidence("dynamic")], TimeoutError("provider secret")],
        policy=RetrievalResiliencePolicy(
            fresh_ttl_seconds=10,
            maximum_stale_seconds=30,
        ),
    )

    assert retriever.search_with_diagnostics(["query"], limit=3).mode == "primary"
    clock.advance(5)
    degraded = retriever.search_with_diagnostics(["query"], limit=3)

    assert degraded.mode == "cache_fresh"
    assert degraded.fallback_used is True
    assert degraded.degraded_components == ["retriever"]


def test_stale_cache_allows_only_explicit_static_evidence() -> None:
    clock = FakeClock()
    static = _resilient(
        clock,
        [[_evidence("static")], TimeoutError("down")],
        policy=RetrievalResiliencePolicy(
            fresh_ttl_seconds=10,
            maximum_stale_seconds=30,
        ),
    )
    static.search(["static-query"], limit=3)
    clock.advance(20)
    assert static.search_with_diagnostics(["static-query"], limit=3).mode == "cache_stale"

    dynamic_clock = FakeClock()
    dynamic = _resilient(
        dynamic_clock,
        [[_evidence("dynamic")], TimeoutError("down")],
        policy=RetrievalResiliencePolicy(
            fresh_ttl_seconds=10,
            maximum_stale_seconds=30,
        ),
    )
    dynamic.search(["dynamic-query"], limit=3)
    dynamic_clock.advance(20)
    with pytest.raises(RetrievalUnavailableError, match="inadmissible"):
        dynamic.search(["dynamic-query"], limit=3)


def test_cache_key_is_a_fixed_hash_and_does_not_store_query_text() -> None:
    secret = "passport-123456"
    key = InMemoryRetrievalCache.key_for([secret], 10)

    assert len(key) == 64
    assert secret not in key


class SwitchableRetriever:
    def __init__(self, healthy) -> None:
        self.healthy = healthy
        self.failed = False

    def search(self, queries: list[str], *, limit: int) -> list[Evidence]:
        if self.failed:
            raise TimeoutError("raw secret from provider")
        return self.healthy.search(queries, limit=limit)


def test_pipeline_observes_cache_fallback_without_exposing_query() -> None:
    clock = FakeClock()
    primary = SwitchableRetriever(BM25Retriever.from_project(PROJECT_ROOT))
    resilient = ResilientRetriever(
        primary,
        breaker=CircuitBreaker(
            failure_threshold=1,
            recovery_timeout_seconds=30,
            clock=clock,
        ),
        cache=InMemoryRetrievalCache(clock=clock),
    )
    sink = InMemoryTelemetrySink()
    traces = iter(
        [
            "00000000000000000000000000000011",
            "00000000000000000000000000000012",
        ]
    )
    pipeline = EndToEndPlanningPipeline(
        retriever=resilient,
        planning_strategy=DeterministicPlanningStrategy(),
        telemetry_sink=sink,
        trace_id_factory=lambda: next(traces),
    )
    assert pipeline.run(_input(PROJECT_ROOT)).status == "completed"
    primary.failed = True

    degraded = pipeline.run(_input(PROJECT_ROOT))

    assert degraded.status == "completed"
    assert degraded.degraded_components == ["retriever"]
    fallback_events = [
        event
        for event in sink.events
        if event.trace_id == degraded.trace_id
        and event.attributes.get("retrieval_mode") == "cache_fresh"
    ]
    assert len(fallback_events) == 1
