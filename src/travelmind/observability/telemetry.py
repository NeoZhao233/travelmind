from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

TelemetryStatus = Literal["started", "succeeded", "failed", "degraded"]
_ALLOWED_ATTRIBUTES = {
    "candidate_count",
    "cache_age_seconds",
    "circuit_state",
    "degraded_component_count",
    "dropped_attribute_count",
    "estimated_context_tokens",
    "evidence_count",
    "fallback_used",
    "packed_evidence_count",
    "repair_attempts",
    "retrieval_limit",
    "retrieval_mode",
    "status",
    "violation_count",
}


class TelemetryEvent(BaseModel):
    schema_version: int = 1
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    sequence: int = Field(ge=1)
    occurred_at: datetime
    component: str = Field(min_length=1, max_length=64)
    operation: str = Field(min_length=1, max_length=64)
    status: TelemetryStatus
    duration_ms: float | None = Field(default=None, ge=0)
    error_type: str | None = Field(default=None, max_length=96)
    reason_code: str | None = Field(default=None, max_length=96)
    attributes: dict[str, bool | float | int | str | None] = Field(default_factory=dict)


class TelemetrySink(Protocol):
    def emit(self, event: TelemetryEvent) -> None: ...


class InMemoryTelemetrySink:
    def __init__(self) -> None:
        self.events: list[TelemetryEvent] = []

    def emit(self, event: TelemetryEvent) -> None:
        self.events.append(event)


class RunTelemetry:
    """Best-effort per-run telemetry that cannot break the user workflow."""

    def __init__(
        self,
        trace_id: str,
        sink: TelemetrySink | None,
        *,
        clock: Callable[[], float] = perf_counter,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if len(trace_id) != 32 or any(
            character not in "0123456789abcdef" for character in trace_id
        ):
            raise ValueError("trace_id must contain 32 lowercase hexadecimal characters")
        self.trace_id = trace_id
        self._sink = sink
        self.clock = clock
        self._now = now
        self._sequence = 0
        self.degraded = False

    def emit(
        self,
        *,
        component: str,
        operation: str,
        status: TelemetryStatus,
        duration_ms: float | None = None,
        error_type: str | None = None,
        reason_code: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self._sequence += 1
        event = TelemetryEvent(
            trace_id=self.trace_id,
            sequence=self._sequence,
            occurred_at=self._now(),
            component=component,
            operation=operation,
            status=status,
            duration_ms=duration_ms,
            error_type=error_type,
            reason_code=reason_code,
            attributes=_safe_attributes(attributes or {}),
        )
        if self._sink is None:
            return
        try:
            self._sink.emit(event)
        except Exception:
            self.degraded = True

    def span(self, component: str, operation: str, **attributes: Any) -> _TelemetrySpan:
        return _TelemetrySpan(self, component, operation, attributes)


def _safe_attributes(attributes: dict[str, Any]) -> dict[str, bool | float | int | str | None]:
    safe: dict[str, bool | float | int | str | None] = {}
    dropped = 0
    for key, value in attributes.items():
        if key not in _ALLOWED_ATTRIBUTES or not isinstance(
            value, (bool, float, int, str, type(None))
        ):
            dropped += 1
            continue
        safe[key] = value
    if dropped:
        safe["dropped_attribute_count"] = dropped
    return safe


class _TelemetrySpan(AbstractContextManager["_TelemetrySpan"]):
    def __init__(
        self,
        owner: RunTelemetry,
        component: str,
        operation: str,
        attributes: dict[str, Any],
    ) -> None:
        self._owner = owner
        self._component = component
        self._operation = operation
        self.attributes = attributes
        self._started = 0.0

    def __enter__(self) -> _TelemetrySpan:
        self._started = self._owner.clock()
        self._owner.emit(
            component=self._component,
            operation=self._operation,
            status="started",
            attributes=self.attributes,
        )
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        del exc_value, traceback
        duration_ms = max(0.0, (self._owner.clock() - self._started) * 1000)
        self._owner.emit(
            component=self._component,
            operation=self._operation,
            status="failed" if exc_type is not None else "succeeded",
            duration_ms=duration_ms,
            error_type=exc_type.__name__ if exc_type is not None else None,
            attributes=self.attributes,
        )
        return False
