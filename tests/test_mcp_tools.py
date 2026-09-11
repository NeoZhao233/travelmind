from __future__ import annotations

import asyncio

import pytest
from mcp import Client

from travelmind.mcp import InProcessMCPCaller, MCPToolRegistry, create_travelmind_mcp_server
from travelmind.runtime.models import ToolResponse
from travelmind.runtime.tools import DictToolRegistry


def _registry() -> DictToolRegistry:
    return DictToolRegistry(
        {
            "candidate_search": lambda arguments: ToolResponse(
                payload={"evidence_count": 1, "query": arguments["query"]},
                evidence_ids=["candidate-evidence"],
            ),
            "availability": lambda arguments: ToolResponse(
                payload={"place_id": arguments["place_id"], "status": "open"},
                evidence_ids=["availability-evidence"],
            ),
            "booking": lambda arguments: ToolResponse(
                payload={"place_id": arguments["place_id"], "bookable": True},
                evidence_ids=["booking-evidence"],
            ),
            "travel_time": lambda arguments: ToolResponse(
                payload={**arguments, "duration_minutes": 30},
                evidence_ids=["travel-evidence"],
            ),
        }
    )


def test_mcp_registry_calls_real_in_process_protocol() -> None:
    server = create_travelmind_mcp_server(_registry())
    registry = MCPToolRegistry(
        InProcessMCPCaller(server),
        {"candidate_search", "availability", "booking", "travel_time"},
    )
    response = registry.get("travel_time")(
        {"origin_place_id": "hotel", "destination_place_id": "palace"}
    )
    assert response.payload == {
        "origin_place_id": "hotel",
        "destination_place_id": "palace",
        "duration_minutes": 30,
    }
    with pytest.raises(PermissionError, match="not allowlisted"):
        registry.get("delete_booking")


def test_mcp_server_publishes_typed_tools_and_policy_resource() -> None:
    async def inspect_server() -> tuple[set[str], str, bool]:
        server = create_travelmind_mcp_server(_registry())
        async with Client(server) as client:
            tools = await client.list_tools()
            resource = await client.read_resource("travelmind://harness/tool-policy")
        names = {tool.name for tool in tools.tools}
        policy_text = str(resource.contents[0].text)
        search_tool = next(tool for tool in tools.tools if tool.name == "candidate_search")
        return names, policy_text, bool(search_tool.annotations.read_only_hint)

    names, policy_text, read_only = asyncio.run(inspect_server())
    assert names == {"candidate_search", "availability", "booking", "travel_time"}
    assert '"cache_ttl_seconds": 900' in policy_text
    assert read_only is True
