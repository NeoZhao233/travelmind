from __future__ import annotations

import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from travelmind.mcp import InProcessMCPCaller, MCPToolRegistry, create_travelmind_mcp_server
from travelmind.runtime.builder import build_travel_runtime_graph
from travelmind.runtime.cache import CachingToolRegistry, InMemoryToolCache, RedisToolCache
from travelmind.runtime.harness import DEFAULT_TRAVEL_TOOL_POLICIES, GovernedToolRegistry
from travelmind.runtime.models import ToolResponse
from travelmind.runtime.policies import DeterministicMultiStepRuntimePlanner
from travelmind.runtime.tools import DictToolRegistry
from travelmind.schemas import Activity, DayPlan, Evidence, Itinerary, TravelRequest


class _HarnessTools:
    def __init__(self, *, booking_error: bool = False, disconnected: bool = False) -> None:
        self.calls: Counter[str] = Counter()
        self.booking_error = booking_error
        self.disconnected = disconnected

    def _before(self, name: str) -> None:
        self.calls[name] += 1
        if self.disconnected:
            raise ConnectionError("sanitized local tool outage")

    def candidate_search(self, arguments: dict[str, Any]) -> ToolResponse:
        self._before("candidate_search")
        return ToolResponse(
            payload={"evidence_count": 2, "query": arguments["query"]},
            evidence_ids=["candidate-search-evidence"],
        )

    def availability(self, arguments: dict[str, Any]) -> ToolResponse:
        self._before("availability")
        place_id = str(arguments["place_id"])
        return ToolResponse(
            payload={"place_id": place_id, "name": place_id, "status": "open"},
            evidence_ids=[f"{place_id}-availability"],
        )

    def booking(self, arguments: dict[str, Any]) -> ToolResponse:
        self._before("booking")
        if self.booking_error:
            raise PermissionError("sanitized booking policy rejection")
        place_id = str(arguments["place_id"])
        return ToolResponse(
            payload={"place_id": place_id, "bookable": True},
            evidence_ids=[f"{place_id}-booking"],
        )

    def travel_time(self, arguments: dict[str, Any]) -> ToolResponse:
        self._before("travel_time")
        return ToolResponse(
            payload={**arguments, "duration_minutes": 30},
            evidence_ids=[f"{arguments['destination_place_id']}-travel"],
        )

    def registry(self) -> DictToolRegistry:
        return DictToolRegistry(
            {
                "candidate_search": self.candidate_search,
                "availability": self.availability,
                "booking": self.booking,
                "travel_time": self.travel_time,
            }
        )


class _ObservationPlanner:
    def generate(self, request: TravelRequest, evidence: list[Evidence]) -> Itinerary:
        del request
        available = [item for item in evidence if item.metadata.get("status") == "open"]
        selected = available[-1]
        start = datetime(2026, 10, 1, 9, tzinfo=UTC)
        place_id = str(selected.metadata["place_id"])
        return Itinerary(
            days=[
                DayPlan(
                    day=1,
                    activities=[
                        Activity(
                            place_id=place_id,
                            name=str(selected.metadata["name"]),
                            start_at=start,
                            end_at=start + timedelta(hours=2),
                            estimated_cost=0,
                            evidence_ids=[selected.id],
                        )
                    ],
                )
            ],
            estimated_total_cost=0,
            assumptions=["Generated only from successful harness observations."],
        )


class _DisconnectedMCPCaller:
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        del name, arguments
        raise ConnectionError("sanitized MCP transport outage")


def _run_runtime(registry: Any) -> tuple[dict[str, Any], float]:
    graph = build_travel_runtime_graph(
        runtime_planner=DeterministicMultiStepRuntimePlanner(
            origin_place_id="hotel",
            primary_place_id="forbidden-city",
            fallback_place_id="national-museum",
        ),
        tool_registry=registry,
        itinerary_planner=_ObservationPlanner(),
        max_replans=1,
        max_tool_attempts=2,
        max_tool_calls=12,
    )
    started = time.perf_counter()
    result = graph.invoke(
        {
            "request": TravelRequest(
                query="从酒店出发规划一个历史文化景点的一日游",
                constraints={"days": 1, "budget": 100},
            )
        }
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    return result, elapsed_ms


def _runtime_row(name: str, result: dict[str, Any], latency_ms: float) -> dict[str, Any]:
    return {
        "scenario": name,
        "status": result["status"],
        "replans": result["replan_count"],
        "tool_calls": result["tool_call_count"],
        "safe_stop": result["status"] == "failed" and result.get("itinerary") is None,
        "error_types": sorted(
            {
                observation.error_type
                for observation in result["observations"]
                if observation.error_type is not None
            }
        ),
        "latency_ms": round(latency_ms, 3),
    }


def run_harness_experiment(root: Path) -> dict[str, Any]:
    del root
    protocol_tools = _HarnessTools()
    protocol_registry = MCPToolRegistry(
        InProcessMCPCaller(create_travelmind_mcp_server(protocol_tools.registry())),
        set(DEFAULT_TRAVEL_TOOL_POLICIES),
    )
    protocol_result, protocol_latency = _run_runtime(protocol_registry)

    fallback_tools = _HarnessTools()
    transport_registry = GovernedToolRegistry(
        MCPToolRegistry(_DisconnectedMCPCaller(), set(DEFAULT_TRAVEL_TOOL_POLICIES)),
        DEFAULT_TRAVEL_TOOL_POLICIES,
        fallback=fallback_tools.registry(),
    )
    transport_result, transport_latency = _run_runtime(transport_registry)

    rejected_tools = _HarnessTools(booking_error=True)
    business_registry = GovernedToolRegistry(
        MCPToolRegistry(
            InProcessMCPCaller(create_travelmind_mcp_server(rejected_tools.registry())),
            set(DEFAULT_TRAVEL_TOOL_POLICIES),
        ),
        DEFAULT_TRAVEL_TOOL_POLICIES,
        fallback=_HarnessTools().registry(),
    )
    business_result, business_latency = _run_runtime(business_registry)

    dual_registry = GovernedToolRegistry(
        MCPToolRegistry(_DisconnectedMCPCaller(), set(DEFAULT_TRAVEL_TOOL_POLICIES)),
        DEFAULT_TRAVEL_TOOL_POLICIES,
        fallback=_HarnessTools(disconnected=True).registry(),
    )
    dual_result, dual_latency = _run_runtime(dual_registry)

    cache_tools = _HarnessTools()
    cached = CachingToolRegistry(
        cache_tools.registry(), DEFAULT_TRAVEL_TOOL_POLICIES, InMemoryToolCache()
    )
    cached.get("candidate_search")({"query": "北京历史文化"})
    cached.get("candidate_search")({"query": "北京历史文化"})

    redis_bypass_tools = _HarnessTools()

    class _BrokenRedis:
        def get(self, key: str) -> None:
            del key
            raise ConnectionError("sanitized Redis outage")

        def set(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise ConnectionError("sanitized Redis outage")

    redis_bypass = CachingToolRegistry(
        redis_bypass_tools.registry(),
        DEFAULT_TRAVEL_TOOL_POLICIES,
        RedisToolCache(_BrokenRedis()),
    )
    redis_bypass_response = redis_bypass.get("candidate_search")({"query": "北京历史文化"})

    checks = {
        "official_mcp_protocol_completed": protocol_result["status"] == "completed",
        "mcp_transport_outage_used_read_only_fallback": (
            transport_result["status"] == "completed"
            and len([record for record in transport_registry.records if record.route == "fallback"])
            == 4
        ),
        "remote_business_error_was_not_masked_as_transport_fallback": (
            business_result["status"] == "completed"
            and business_result["replan_count"] == 1
            and not any(record.route == "fallback" for record in business_registry.records)
            and any(
                record.tool_name == "booking" and record.outcome == "permanent_error"
                for record in business_registry.records
            )
        ),
        "mcp_and_local_failure_stopped_safely": (
            dual_result["status"] == "failed" and dual_result.get("itinerary") is None
        ),
        "cache_reused_only_successful_read": (
            cached.hits == 1 and cache_tools.calls["candidate_search"] == 1
        ),
        "redis_cache_outage_bypassed_without_tool_outage": (
            redis_bypass_response.outcome == "success"
            and redis_bypass_tools.calls["candidate_search"] == 1
        ),
    }
    return {
        "schema_version": 1,
        "experiment": "stage13-agent-harness-mcp-redis-fault-drill",
        "configuration": {
            "mcp_transport": "official-sdk-in-process",
            "mcp_protocol_revision": "2026-07-28",
            "redis_mode": "fault-injected-cache-client",
            "tool_count": 4,
            "max_replans": 1,
            "max_tool_attempts": 2,
        },
        "checks": checks,
        "metrics": {
            "check_pass_rate": sum(checks.values()) / len(checks),
            "mcp_protocol_completion_rate": float(protocol_result["status"] == "completed"),
            "transport_fallback_recovery_rate": float(transport_result["status"] == "completed"),
            "dual_path_safe_stop_rate": float(
                dual_result["status"] == "failed" and dual_result.get("itinerary") is None
            ),
            "cache_hit_rate": cached.hits / (cached.hits + cached.misses),
            "redis_cache_outage_bypass_rate": float(redis_bypass_response.outcome == "success"),
        },
        "runtime_scenarios": [
            _runtime_row("official_mcp_protocol", protocol_result, protocol_latency),
            _runtime_row("mcp_transport_local_fallback", transport_result, transport_latency),
            _runtime_row("remote_business_error_replan", business_result, business_latency),
            _runtime_row("mcp_and_local_safe_stop", dual_result, dual_latency),
        ],
        "tool_diagnostics": {
            "protocol_calls": dict(protocol_tools.calls),
            "fallback_calls": dict(fallback_tools.calls),
            "transport_routes": [
                record.model_dump(mode="json") for record in transport_registry.records
            ],
            "business_routes": [
                record.model_dump(mode="json") for record in business_registry.records
            ],
            "cache_hits": cached.hits,
            "cache_misses": cached.misses,
        },
        "limitations": [
            "MCP uses the official in-process transport, not a remote network deployment.",
            "Redis outage behavior is fault-injected; a live Redis checkpoint drill is separate.",
            "Fixture tools validate harness contracts, not production provider availability.",
            "Latency includes local test overhead and is not a service SLO.",
        ],
    }
