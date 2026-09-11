from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from travelmind.runtime.protocols import Tool, ToolRegistry


class ToolAccess(StrEnum):
    READ_ONLY = "read_only"
    MUTATING = "mutating"


class ToolPolicy(BaseModel):
    """Harness policy kept separate from model-authored tool arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    access: ToolAccess
    idempotent: bool
    cacheable: bool = False
    fallback_allowed: bool = False
    cache_ttl_seconds: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def safe_cache_and_fallback_policy(self) -> ToolPolicy:
        if (self.cacheable or self.fallback_allowed) and (
            self.access != ToolAccess.READ_ONLY or not self.idempotent
        ):
            raise ValueError("cache and fallback require a read-only idempotent tool")
        if self.cacheable != (self.cache_ttl_seconds is not None):
            raise ValueError("cacheable tools require a TTL and non-cacheable tools forbid one")
        return self


class ToolInvocationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str
    route: str
    outcome: str
    error_type: str | None = None


DEFAULT_TRAVEL_TOOL_POLICIES: dict[str, ToolPolicy] = {
    "candidate_search": ToolPolicy(
        name="candidate_search",
        access=ToolAccess.READ_ONLY,
        idempotent=True,
        cacheable=True,
        fallback_allowed=True,
        cache_ttl_seconds=900,
    ),
    "availability": ToolPolicy(
        name="availability",
        access=ToolAccess.READ_ONLY,
        idempotent=True,
        cacheable=True,
        fallback_allowed=True,
        cache_ttl_seconds=60,
    ),
    "booking": ToolPolicy(
        name="booking",
        access=ToolAccess.READ_ONLY,
        idempotent=True,
        cacheable=False,
        fallback_allowed=True,
    ),
    "travel_time": ToolPolicy(
        name="travel_time",
        access=ToolAccess.READ_ONLY,
        idempotent=True,
        cacheable=True,
        fallback_allowed=True,
        cache_ttl_seconds=120,
    ),
}


class GovernedToolRegistry:
    """Allowlist tools and use local fallback only for transport-level failures."""

    def __init__(
        self,
        primary: ToolRegistry,
        policies: Mapping[str, ToolPolicy],
        *,
        fallback: ToolRegistry | None = None,
        transport_errors: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError),
    ) -> None:
        self._primary = primary
        self._policies = dict(policies)
        self._fallback = fallback
        self._transport_errors = transport_errors
        self.records: list[ToolInvocationRecord] = []

    def policy(self, name: str) -> ToolPolicy:
        try:
            return self._policies[name]
        except KeyError as exc:
            raise PermissionError(f"tool is not allowlisted: {name}") from exc

    def get(self, name: str) -> Tool:
        policy = self.policy(name)
        primary_tool = self._primary.get(name)

        def invoke(arguments: dict[str, Any]):
            try:
                response = primary_tool(arguments)
            except self._transport_errors as exc:
                self.records.append(
                    ToolInvocationRecord(
                        tool_name=name,
                        route="primary",
                        outcome="transport_error",
                        error_type=type(exc).__name__,
                    )
                )
                if not policy.fallback_allowed or self._fallback is None:
                    raise
                response = self._fallback.get(name)(arguments)
                self.records.append(
                    ToolInvocationRecord(
                        tool_name=name,
                        route="fallback",
                        outcome=_tool_outcome(response),
                    )
                )
                return response
            self.records.append(
                ToolInvocationRecord(
                    tool_name=name,
                    route="primary",
                    outcome=_tool_outcome(response),
                )
            )
            return response

        return invoke


def _tool_outcome(response: object) -> str:
    value = getattr(response, "outcome", None)
    if value is None and isinstance(response, dict):
        value = response.get("outcome")
    return str(getattr(value, "value", value) or "returned")
