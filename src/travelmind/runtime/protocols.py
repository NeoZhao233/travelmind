from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from travelmind.runtime.models import (
    ExecutionPlan,
    FailureAttribution,
    ToolObservation,
    ToolResponse,
)
from travelmind.schemas import TravelRequest


class RuntimePlanner(Protocol):
    def plan(
        self,
        request: TravelRequest,
        *,
        observations: list[ToolObservation],
        previous_plan: ExecutionPlan | None,
        failure: FailureAttribution | None,
    ) -> ExecutionPlan: ...


Tool = Callable[[dict[str, Any]], ToolResponse | dict[str, Any]]


class ToolRegistry(Protocol):
    def get(self, name: str) -> Tool: ...
