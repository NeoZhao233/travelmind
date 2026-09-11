from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

from travelmind.runtime.harness import ToolPolicy
from travelmind.runtime.models import ToolOutcome, ToolResponse
from travelmind.runtime.protocols import Tool, ToolRegistry


class ToolCache(Protocol):
    def get(self, key: str) -> ToolResponse | None: ...

    def set(self, key: str, value: ToolResponse, *, ttl_seconds: int) -> None: ...


def tool_cache_key(tool_name: str, arguments: Mapping[str, Any]) -> str:
    canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{tool_name}:{canonical}".encode()).hexdigest()
    return f"travelmind:tool-cache:{tool_name}:{digest}"


class InMemoryToolCache:
    """Deterministic test cache; production TTL semantics belong to Redis."""

    def __init__(self) -> None:
        self.values: dict[str, ToolResponse] = {}

    def get(self, key: str) -> ToolResponse | None:
        value = self.values.get(key)
        return value.model_copy(deep=True) if value is not None else None

    def set(self, key: str, value: ToolResponse, *, ttl_seconds: int) -> None:
        del ttl_seconds
        self.values[key] = value.model_copy(deep=True)


class RedisToolCache:
    """Best-effort Redis cache; cache outages never become tool outages."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    def get(self, key: str) -> ToolResponse | None:
        try:
            raw = self._redis.get(key)
        except Exception:
            return None
        if raw is None:
            return None
        try:
            return ToolResponse.model_validate_json(raw)
        except (TypeError, ValueError):
            return None

    def set(self, key: str, value: ToolResponse, *, ttl_seconds: int) -> None:
        try:
            self._redis.set(key, value.model_dump_json(), ex=ttl_seconds)
        except Exception:
            return


class CachingToolRegistry:
    """Cache only successful calls explicitly declared safe by harness policy."""

    def __init__(
        self,
        delegate: ToolRegistry,
        policies: Mapping[str, ToolPolicy],
        cache: ToolCache,
    ) -> None:
        self._delegate = delegate
        self._policies = dict(policies)
        self._cache = cache
        self.hits = 0
        self.misses = 0

    def get(self, name: str) -> Tool:
        tool = self._delegate.get(name)
        policy = self._policies[name]
        if not policy.cacheable:
            return tool

        def invoke(arguments: dict[str, Any]):
            key = tool_cache_key(name, arguments)
            cached = self._cache.get(key)
            if cached is not None:
                self.hits += 1
                return cached
            self.misses += 1
            raw = tool(arguments)
            response = raw if isinstance(raw, ToolResponse) else ToolResponse.model_validate(raw)
            if response.outcome == ToolOutcome.SUCCESS:
                self._cache.set(
                    key,
                    response,
                    ttl_seconds=policy.cache_ttl_seconds or 1,
                )
            return response

        return invoke
