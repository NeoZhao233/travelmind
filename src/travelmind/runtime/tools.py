from __future__ import annotations

from collections.abc import Mapping

from travelmind.runtime.protocols import Tool


class DictToolRegistry:
    """Small injectable registry; transport-specific clients stay behind tool callables."""

    def __init__(self, tools: Mapping[str, Tool]) -> None:
        self._tools = dict(tools)

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise LookupError(f"tool is not registered: {name}") from exc
