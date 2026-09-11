from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel, ConfigDict, Field, model_validator

_TRAVELMIND_MSGPACK_ALLOWLIST = [
    ("travelmind.agentic.models", "EvidenceAssessment"),
    ("travelmind.agentic.models", "QueryIntent"),
    ("travelmind.agentic.models", "RoutingDecision"),
    ("travelmind.agentic.models", "TrajectoryEvent"),
    ("travelmind.schemas", "Activity"),
    ("travelmind.schemas", "ConstraintViolation"),
    ("travelmind.schemas", "DayPlan"),
    ("travelmind.schemas", "Evidence"),
    ("travelmind.schemas", "Itinerary"),
    ("travelmind.schemas", "TravelConstraints"),
    ("travelmind.schemas", "TravelRequest"),
]


class CheckpointBackend(StrEnum):
    MEMORY = "memory"
    SQLITE = "sqlite"
    REDIS = "redis"


class CheckpointSettings(BaseModel):
    """Explicit startup selection; checkpoint failures never switch stores mid-run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: CheckpointBackend = CheckpointBackend.MEMORY
    sqlite_path: Path | None = None
    redis_url: str | None = None
    redis_ttl_minutes: int | None = Field(default=60, ge=1)

    @model_validator(mode="after")
    def required_backend_location(self) -> CheckpointSettings:
        if self.backend == CheckpointBackend.SQLITE and self.sqlite_path is None:
            raise ValueError("sqlite backend requires sqlite_path")
        if self.backend == CheckpointBackend.REDIS and not self.redis_url:
            raise ValueError("redis backend requires redis_url")
        return self


def build_in_memory_checkpointer() -> InMemorySaver:
    """Build a strict-type logical-resume saver; it is not process-durable."""

    return InMemorySaver(serde=_serializer())


def _serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(
        allowed_msgpack_modules=_TRAVELMIND_MSGPACK_ALLOWLIST,
    )


@contextmanager
def open_sqlite_checkpointer(path: Path) -> Iterator[object]:
    """Open a durable local checkpointer with strict types and bounded lock waits."""

    from langgraph.checkpoint.sqlite import SqliteSaver

    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved, check_same_thread=False, timeout=5)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        saver = SqliteSaver(connection, serde=_serializer())
        saver.setup()
        resolved.chmod(0o600)
        yield saver
    finally:
        connection.close()


@contextmanager
def open_redis_checkpointer(
    redis_url: str,
    *,
    ttl_minutes: int | None = 60,
) -> Iterator[object]:
    """Open the optional shared Redis saver; connection failure is explicit to callers."""

    if ttl_minutes is not None and ttl_minutes < 1:
        raise ValueError("Redis checkpoint TTL must be positive or None")
    from langgraph.checkpoint.redis import RedisSaver

    ttl = None if ttl_minutes is None else {"default_ttl": ttl_minutes, "refresh_on_read": True}
    with RedisSaver.from_conn_string(redis_url, ttl=ttl) as saver:
        saver.setup()
        yield saver


@contextmanager
def open_checkpointer(settings: CheckpointSettings) -> Iterator[object]:
    """Open the selected backend without unsafe automatic state-store failover."""

    if settings.backend == CheckpointBackend.MEMORY:
        yield build_in_memory_checkpointer()
        return
    if settings.backend == CheckpointBackend.SQLITE:
        assert settings.sqlite_path is not None
        with open_sqlite_checkpointer(settings.sqlite_path) as saver:
            yield saver
        return
    assert settings.redis_url is not None
    with open_redis_checkpointer(
        settings.redis_url,
        ttl_minutes=settings.redis_ttl_minutes,
    ) as saver:
        yield saver
