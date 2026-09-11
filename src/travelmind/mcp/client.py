from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from mcp import Client

from travelmind.runtime.models import ToolResponse
from travelmind.runtime.protocols import Tool


class MCPToolCallError(RuntimeError):
    """The remote tool ran but returned an MCP-level error."""


class MCPToolCaller(Protocol):
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class InProcessMCPCaller:
    """Synchronous bridge for the sync LangGraph runtime using real in-memory MCP."""

    def __init__(self, server: Any, *, timeout_seconds: float = 5.0) -> None:
        self._server = server
        self._timeout_seconds = timeout_seconds

    async def _call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with Client(self._server, raise_exceptions=False) as client:
            result = await client.call_tool(
                name,
                arguments,
                read_timeout_seconds=self._timeout_seconds,
            )
        if result.is_error:
            raise MCPToolCallError(f"MCP tool failed: {name}")
        if result.structured_content is not None:
            return dict(result.structured_content)
        for block in result.content:
            text = getattr(block, "text", None)
            if text:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
        raise MCPToolCallError(f"MCP tool returned no structured object: {name}")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            return asyncio.run(self._call(name, arguments))

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return run()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result(timeout=self._timeout_seconds + 1)


class MCPToolRegistry:
    def __init__(self, caller: MCPToolCaller, allowed_tools: set[str]) -> None:
        self._caller = caller
        self._allowed_tools = frozenset(allowed_tools)

    def get(self, name: str) -> Tool:
        if name not in self._allowed_tools:
            raise PermissionError(f"MCP tool is not allowlisted: {name}")

        def invoke(arguments: dict[str, Any]) -> ToolResponse:
            return ToolResponse.model_validate(self._caller.call_tool(name, arguments))

        return invoke
