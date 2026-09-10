from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Literal

from pydantic import BaseModel, Field

from travelmind.retrieval.base import Retriever
from travelmind.schemas import Evidence

CircuitState = Literal["closed", "open", "half_open"]
RetrievalMode = Literal["primary", "cache_fresh", "cache_stale"]


class CircuitOpenError(RuntimeError):
    """A dependency call was rejected because its circuit is open."""


class RetrievalUnavailableError(RuntimeError):
    """Primary retrieval failed and no policy-compliant cache entry exists."""


class CircuitSnapshot(BaseModel):
    state: CircuitState
    consecutive_failures: int = Field(ge=0)
    half_open_probe_in_flight: bool


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 30,
        clock: Callable[[], float] = monotonic,
        transient_exceptions: tuple[type[Exception], ...] = (
            TimeoutError,
            ConnectionError,
        ),
    ) -> None:
        if failure_threshold < 1 or recovery_timeout_seconds <= 0:
            raise ValueError("invalid circuit-breaker threshold or recovery timeout")
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self._clock = clock
        self._transient_exceptions = transient_exceptions
        self._state: CircuitState = "closed"
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._lock = threading.Lock()

    def _acquire(self) -> None:
        with self._lock:
            if self._state == "closed":
                return
            if self._state == "open":
                assert self._opened_at is not None
                if self._clock() - self._opened_at < self.recovery_timeout_seconds:
                    raise CircuitOpenError("dependency circuit is open")
                self._state = "half_open"
            if self._probe_in_flight:
                raise CircuitOpenError("dependency half-open probe is already running")
            self._probe_in_flight = True

    def _success(self) -> None:
        with self._lock:
            self._state = "closed"
            self._failures = 0
            self._opened_at = None
            self._probe_in_flight = False

    def _failure(self, exc: Exception) -> None:
        with self._lock:
            if not isinstance(exc, self._transient_exceptions):
                self._probe_in_flight = False
                if self._state == "half_open":
                    self._state = "closed"
                return
            self._failures += 1
            if self._state == "half_open" or self._failures >= self.failure_threshold:
                self._state = "open"
                self._opened_at = self._clock()
            self._probe_in_flight = False

    def call(self, operation: Callable[[], list[Evidence]]) -> list[Evidence]:
        self._acquire()
        try:
            result = operation()
        except Exception as exc:
            self._failure(exc)
            raise
        self._success()
        return result

    def snapshot(self) -> CircuitSnapshot:
        with self._lock:
            return CircuitSnapshot(
                state=self._state,
                consecutive_failures=self._failures,
                half_open_probe_in_flight=self._probe_in_flight,
            )


@dataclass(frozen=True)
class _CacheEntry:
    stored_at: float
    evidence: tuple[Evidence, ...]


class InMemoryRetrievalCache:
    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._entries: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key_for(queries: list[str], limit: int) -> str:
        normalized = [" ".join(query.casefold().split()) for query in queries]
        payload = json.dumps([normalized, limit], ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def put(self, key: str, evidence: list[Evidence]) -> None:
        snapshot = tuple(item.model_copy(deep=True) for item in evidence)
        with self._lock:
            self._entries[key] = _CacheEntry(self._clock(), snapshot)

    def get(self, key: str) -> tuple[list[Evidence], float] | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            return (
                [item.model_copy(deep=True) for item in entry.evidence],
                max(0.0, self._clock() - entry.stored_at),
            )


class RetrievalResiliencePolicy(BaseModel):
    fresh_ttl_seconds: float = Field(default=30, gt=0)
    maximum_stale_seconds: float = Field(default=300, gt=0)
    stale_allowed_freshness_classes: frozenset[str] = frozenset({"static"})


class ResilientRetrievalResult(BaseModel):
    evidence: list[Evidence]
    mode: RetrievalMode
    degraded_components: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    cache_age_seconds: float | None = Field(default=None, ge=0)
    circuit: CircuitSnapshot


class ResilientRetriever:
    """Circuit-break a retriever and use only freshness-policy-compliant cached evidence."""

    def __init__(
        self,
        primary: Retriever,
        *,
        breaker: CircuitBreaker,
        cache: InMemoryRetrievalCache,
        policy: RetrievalResiliencePolicy | None = None,
    ) -> None:
        self._primary = primary
        self._breaker = breaker
        self._cache = cache
        self._policy = policy or RetrievalResiliencePolicy()
        if self._policy.maximum_stale_seconds < self._policy.fresh_ttl_seconds:
            raise ValueError("maximum stale age must be at least the fresh TTL")

    def search_with_diagnostics(
        self, queries: list[str], *, limit: int
    ) -> ResilientRetrievalResult:
        key = self._cache.key_for(queries, limit)
        try:
            evidence = self._breaker.call(lambda: self._primary.search(queries, limit=limit))
        except (CircuitOpenError, TimeoutError, ConnectionError) as exc:
            cached = self._cache.get(key)
            if cached is None:
                raise RetrievalUnavailableError("retrieval unavailable and cache miss") from exc
            evidence, age = cached
            if age <= self._policy.fresh_ttl_seconds:
                mode: RetrievalMode = "cache_fresh"
            else:
                freshness = {str(item.metadata.get("freshness", "unknown")) for item in evidence}
                if (
                    age > self._policy.maximum_stale_seconds
                    or not freshness
                    or not freshness <= self._policy.stale_allowed_freshness_classes
                ):
                    raise RetrievalUnavailableError(
                        "retrieval unavailable and cached evidence is inadmissible"
                    ) from exc
                mode = "cache_stale"
            return ResilientRetrievalResult(
                evidence=evidence,
                mode=mode,
                degraded_components=["retriever"],
                fallback_used=True,
                cache_age_seconds=age,
                circuit=self._breaker.snapshot(),
            )
        self._cache.put(key, evidence)
        return ResilientRetrievalResult(
            evidence=evidence,
            mode="primary",
            circuit=self._breaker.snapshot(),
        )

    def search(self, queries: list[str], *, limit: int) -> list[Evidence]:
        return self.search_with_diagnostics(queries, limit=limit).evidence
