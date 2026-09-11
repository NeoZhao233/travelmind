from __future__ import annotations

import json
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from travelmind.runtime.harness import DEFAULT_TRAVEL_TOOL_POLICIES
from travelmind.runtime.models import ToolOutcome, ToolResponse
from travelmind.runtime.protocols import ToolRegistry


def _json_response(raw: ToolResponse | dict[str, Any]) -> dict[str, Any]:
    response = raw if isinstance(raw, ToolResponse) else ToolResponse.model_validate(raw)
    return response.model_dump(mode="json")


def _invoke_tool(
    tool_registry: ToolRegistry,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Return typed, sanitized failures instead of leaking provider exception details."""

    try:
        return _json_response(tool_registry.get(name)(arguments))
    except (TimeoutError, ConnectionError):
        return _json_response(ToolResponse(outcome=ToolOutcome.TRANSIENT_ERROR))
    except Exception:
        return _json_response(ToolResponse(outcome=ToolOutcome.PERMANENT_ERROR))


def create_travelmind_mcp_server(tool_registry: ToolRegistry) -> MCPServer:
    """Expose the four runtime tools through the official MCP protocol layer."""

    server = MCPServer(
        "travelmind-tools",
        description="Governed read-only tools for the TravelMind planning harness.",
        version="0.1.0",
    )
    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(name="candidate_search", annotations=read_only, structured_output=True)
    def candidate_search(query: str) -> dict[str, Any]:
        """Search the governed travel corpus for candidate places."""

        return _invoke_tool(tool_registry, "candidate_search", {"query": query})

    @server.tool(name="availability", annotations=read_only, structured_output=True)
    def availability(place_id: str) -> dict[str, Any]:
        """Check whether a candidate place is available for the requested plan."""

        return _invoke_tool(tool_registry, "availability", {"place_id": place_id})

    @server.tool(name="booking", annotations=read_only, structured_output=True)
    def booking(place_id: str) -> dict[str, Any]:
        """Read booking requirements; this tool does not create a reservation."""

        return _invoke_tool(tool_registry, "booking", {"place_id": place_id})

    @server.tool(name="travel_time", annotations=read_only, structured_output=True)
    def travel_time(origin_place_id: str, destination_place_id: str) -> dict[str, Any]:
        """Estimate travel duration between two known places."""

        return _invoke_tool(
            tool_registry,
            "travel_time",
            {
                "origin_place_id": origin_place_id,
                "destination_place_id": destination_place_id,
            },
        )

    @server.resource(
        "travelmind://harness/tool-policy",
        name="travelmind-tool-policy",
        mime_type="application/json",
    )
    def tool_policy() -> str:
        """Publish non-secret cache and side-effect policy for host inspection."""

        payload = {
            name: policy.model_dump(mode="json")
            for name, policy in DEFAULT_TRAVEL_TOOL_POLICIES.items()
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    return server
