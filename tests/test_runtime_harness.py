from __future__ import annotations

from collections import Counter

import pytest

from travelmind.execution import (
    CheckpointBackend,
    CheckpointSettings,
    open_checkpointer,
    open_redis_checkpointer,
)
from travelmind.runtime.cache import CachingToolRegistry, InMemoryToolCache, RedisToolCache
from travelmind.runtime.harness import (
    DEFAULT_TRAVEL_TOOL_POLICIES,
    GovernedToolRegistry,
    ToolAccess,
    ToolPolicy,
)
from travelmind.runtime.models import ToolOutcome, ToolResponse
from travelmind.runtime.tools import DictToolRegistry


def _success(arguments: dict[str, object]) -> ToolResponse:
    return ToolResponse(payload={"arguments": arguments}, evidence_ids=["evidence-1"])


def test_tool_policy_forbids_caching_or_fallback_for_mutations() -> None:
    with pytest.raises(ValueError, match="read-only idempotent"):
        ToolPolicy(
            name="create_booking",
            access=ToolAccess.MUTATING,
            idempotent=False,
            cacheable=True,
            cache_ttl_seconds=60,
        )
    with pytest.raises(ValueError, match="read-only idempotent"):
        ToolPolicy(
            name="create_booking",
            access=ToolAccess.MUTATING,
            idempotent=False,
            fallback_allowed=True,
        )


def test_governed_registry_allows_only_declared_tools() -> None:
    registry = GovernedToolRegistry(
        DictToolRegistry({"candidate_search": _success}),
        {"candidate_search": DEFAULT_TRAVEL_TOOL_POLICIES["candidate_search"]},
    )
    assert registry.get("candidate_search")({"query": "北京"}).payload
    with pytest.raises(PermissionError, match="not allowlisted"):
        registry.get("unknown")


def test_governed_registry_falls_back_only_on_transport_error() -> None:
    def disconnected(arguments: dict[str, object]) -> ToolResponse:
        del arguments
        raise ConnectionError("secret endpoint")

    registry = GovernedToolRegistry(
        DictToolRegistry({"candidate_search": disconnected}),
        {"candidate_search": DEFAULT_TRAVEL_TOOL_POLICIES["candidate_search"]},
        fallback=DictToolRegistry({"candidate_search": _success}),
    )
    result = registry.get("candidate_search")({"query": "北京"})
    assert result.evidence_ids == ["evidence-1"]
    assert [record.route for record in registry.records] == ["primary", "fallback"]
    assert registry.records[0].error_type == "ConnectionError"

    def remote_business_error(arguments: dict[str, object]) -> ToolResponse:
        del arguments
        raise RuntimeError("remote tool rejected request")

    no_fallback = GovernedToolRegistry(
        DictToolRegistry({"candidate_search": remote_business_error}),
        {"candidate_search": DEFAULT_TRAVEL_TOOL_POLICIES["candidate_search"]},
        fallback=DictToolRegistry({"candidate_search": _success}),
    )
    with pytest.raises(RuntimeError, match="rejected"):
        no_fallback.get("candidate_search")({"query": "北京"})
    assert no_fallback.records == []


def test_cache_reuses_success_but_not_errors_or_uncacheable_tools() -> None:
    calls: Counter[str] = Counter()

    def search(arguments: dict[str, object]) -> ToolResponse:
        calls["search"] += 1
        return ToolResponse(payload={"arguments": arguments}, evidence_ids=["search-evidence"])

    def booking(arguments: dict[str, object]) -> ToolResponse:
        calls["booking"] += 1
        return ToolResponse(payload={"arguments": arguments}, evidence_ids=["booking-evidence"])

    registry = CachingToolRegistry(
        DictToolRegistry({"candidate_search": search, "booking": booking}),
        DEFAULT_TRAVEL_TOOL_POLICIES,
        InMemoryToolCache(),
    )
    first = registry.get("candidate_search")({"query": "北京"})
    second = registry.get("candidate_search")({"query": "北京"})
    registry.get("booking")({"place_id": "palace"})
    registry.get("booking")({"place_id": "palace"})
    assert first == second
    assert calls == Counter({"booking": 2, "search": 1})
    assert (registry.hits, registry.misses) == (1, 1)

    error_calls = Counter()

    def unavailable(arguments: dict[str, object]) -> ToolResponse:
        del arguments
        error_calls["count"] += 1
        return ToolResponse(outcome=ToolOutcome.TRANSIENT_ERROR)

    errors = CachingToolRegistry(
        DictToolRegistry({"candidate_search": unavailable}),
        DEFAULT_TRAVEL_TOOL_POLICIES,
        InMemoryToolCache(),
    )
    errors.get("candidate_search")({"query": "北京"})
    errors.get("candidate_search")({"query": "北京"})
    assert error_calls["count"] == 2


def test_redis_cache_failure_is_best_effort() -> None:
    class BrokenRedis:
        def get(self, key: str) -> None:
            del key
            raise ConnectionError("secret redis endpoint")

        def set(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise ConnectionError("secret redis endpoint")

    calls = Counter()

    def search(arguments: dict[str, object]) -> ToolResponse:
        del arguments
        calls["count"] += 1
        return ToolResponse(payload={"evidence_count": 1}, evidence_ids=["evidence-1"])

    registry = CachingToolRegistry(
        DictToolRegistry({"candidate_search": search}),
        DEFAULT_TRAVEL_TOOL_POLICIES,
        RedisToolCache(BrokenRedis()),
    )
    assert registry.get("candidate_search")({"query": "北京"}).outcome == "success"
    assert calls["count"] == 1


def test_redis_checkpointer_rejects_invalid_ttl_before_connecting() -> None:
    with pytest.raises(ValueError, match="TTL must be positive"):
        with open_redis_checkpointer("redis://127.0.0.1:1/0", ttl_minutes=0):
            pass


def test_checkpoint_backend_selection_is_explicit_and_validated(tmp_path) -> None:
    with pytest.raises(ValueError, match="sqlite_path"):
        CheckpointSettings(backend=CheckpointBackend.SQLITE)
    with pytest.raises(ValueError, match="redis_url"):
        CheckpointSettings(backend=CheckpointBackend.REDIS)

    settings = CheckpointSettings(
        backend=CheckpointBackend.SQLITE,
        sqlite_path=tmp_path / "checkpoint.sqlite3",
    )
    with open_checkpointer(settings) as saver:
        assert saver is not None
    assert settings.sqlite_path.is_file()
