from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from travelmind.runtime.builder import build_travel_runtime_graph
from travelmind.runtime.models import ToolResponse
from travelmind.runtime.policies import DeterministicMultiStepRuntimePlanner
from travelmind.runtime.tools import DictToolRegistry
from travelmind.schemas import Activity, DayPlan, Evidence, Itinerary, TravelRequest


class RuntimeMultiStepCase(BaseModel):
    case_id: str
    fault: Literal[
        "none",
        "primary_booking_failure",
        "primary_travel_failure",
        "primary_and_fallback_travel_failure",
    ]
    recoverable: bool
    expected_status: Literal["completed", "failed"]
    expected_replans: int
    expected_final_place: str | None
    expected_tool_calls: int
    reviewed: bool


class _ObservationAwareItineraryPlanner:
    def generate(self, request: TravelRequest, evidence: list[Evidence]) -> Itinerary:
        del request
        availability = [item for item in evidence if item.metadata.get("status") == "open"]
        selected = availability[-1]
        start = datetime(2026, 10, 1, 9, tzinfo=UTC)
        cost = 60 if selected.metadata["place_id"] == "forbidden-city" else 0
        return Itinerary(
            days=[
                DayPlan(
                    day=1,
                    activities=[
                        Activity(
                            place_id=str(selected.metadata["place_id"]),
                            name=str(selected.metadata["name"]),
                            start_at=start,
                            end_at=start + timedelta(hours=2),
                            estimated_cost=cost,
                            evidence_ids=[selected.id],
                        )
                    ],
                )
            ],
            estimated_total_cost=cost,
            assumptions=["Selected from the latest successful availability observation."],
        )


class _CountingTools:
    def __init__(self, case: RuntimeMultiStepCase) -> None:
        self.case = case
        self.calls = {"candidate_search": 0, "availability": 0, "booking": 0, "travel_time": 0}

    def registry(self) -> DictToolRegistry:
        return DictToolRegistry(
            {
                "candidate_search": self.candidate_search,
                "availability": self.availability,
                "booking": self.booking,
                "travel_time": self.travel_time,
            }
        )

    def candidate_search(self, arguments: dict[str, Any]) -> ToolResponse:
        del arguments
        self.calls["candidate_search"] += 1
        return ToolResponse(
            payload={
                "evidence_count": 2,
                "candidates": ["forbidden-city", "national-museum"],
            },
            evidence_ids=["candidate-search-live"],
        )

    def availability(self, arguments: dict[str, Any]) -> ToolResponse:
        self.calls["availability"] += 1
        place_id = str(arguments["place_id"])
        return ToolResponse(
            payload={
                "place_id": place_id,
                "name": "故宫" if place_id == "forbidden-city" else "中国国家博物馆",
                "status": "open",
            },
            evidence_ids=[f"{place_id}-availability-live"],
        )

    def booking(self, arguments: dict[str, Any]) -> ToolResponse:
        self.calls["booking"] += 1
        if (
            self.case.fault == "primary_booking_failure"
            and arguments["place_id"] == "forbidden-city"
        ):
            raise PermissionError("injected booking credential detail")
        return ToolResponse(
            payload={"place_id": arguments["place_id"], "bookable": True},
            evidence_ids=["forbidden-city-booking-live"],
        )

    def travel_time(self, arguments: dict[str, Any]) -> ToolResponse:
        self.calls["travel_time"] += 1
        destination = str(arguments["destination_place_id"])
        if self.case.fault == "primary_travel_failure" and destination == "forbidden-city":
            raise RuntimeError("injected route contract detail")
        if self.case.fault == "primary_and_fallback_travel_failure":
            raise PermissionError("injected route policy detail")
        return ToolResponse(
            payload={
                "origin_place_id": arguments["origin_place_id"],
                "destination_place_id": destination,
                "duration_minutes": 35,
            },
            evidence_ids=[f"hotel-{destination}-travel-live"],
        )


def load_runtime_multistep_cases(path: Path) -> list[RuntimeMultiStepCase]:
    return [
        RuntimeMultiStepCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_runtime_multistep_case(
    case: RuntimeMultiStepCase,
    *,
    max_replans: int,
    runtime_planner: Any | None = None,
) -> dict[str, Any]:
    tools = _CountingTools(case)
    graph = build_travel_runtime_graph(
        runtime_planner=runtime_planner
        or DeterministicMultiStepRuntimePlanner(
            origin_place_id="hotel",
            primary_place_id="forbidden-city",
            fallback_place_id="national-museum",
        ),
        tool_registry=tools.registry(),
        itinerary_planner=_ObservationAwareItineraryPlanner(),
        max_replans=max_replans,
    )
    result = graph.invoke(
        {
            "request": TravelRequest(
                query="从酒店出发规划一个历史文化景点的一日游",
                constraints={"days": 1, "budget": 100},
            )
        }
    )
    itinerary = result.get("itinerary")
    final_place = (
        itinerary.days[0].activities[0].place_id
        if result["status"] == "completed" and itinerary is not None
        else None
    )
    return {
        "status": result["status"],
        "replans": result["replan_count"],
        "plan_revisions": [plan.revision for plan in result["plan_history"]],
        "tool_calls": result["tool_call_count"],
        "calls_by_tool": tools.calls,
        "retrieval_reused": tools.calls["candidate_search"] == 1,
        "final_place": final_place,
        "safe_stop": result["status"] == "failed" and itinerary is None,
        "trajectory": result["trajectory"],
    }


def run_runtime_multistep_experiment(root: Path) -> dict[str, Any]:
    dataset = root.resolve() / "evals/datasets/runtime_multistep_seed.jsonl"
    cases = load_runtime_multistep_cases(dataset)
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("runtime multi-step case IDs must be unique")
    rows = []
    for case in cases:
        baseline = run_runtime_multistep_case(case, max_replans=0)
        agentic = run_runtime_multistep_case(case, max_replans=1)
        rows.append(
            {
                **case.model_dump(mode="json"),
                "baseline": baseline,
                "agentic": agentic,
            }
        )
    recoverable_failures = [row for row in rows if row["fault"] != "none" and row["recoverable"]]
    unrecoverable = [row for row in rows if not row["recoverable"]]
    metrics = {
        "case_contract_pass_rate": sum(
            row["agentic"]["status"] == row["expected_status"]
            and row["agentic"]["replans"] == row["expected_replans"]
            and row["agentic"]["final_place"] == row["expected_final_place"]
            and row["agentic"]["tool_calls"] == row["expected_tool_calls"]
            for row in rows
        )
        / len(rows),
        "baseline_intermediate_failure_recovery_rate": sum(
            row["baseline"]["status"] == "completed" for row in recoverable_failures
        )
        / len(recoverable_failures),
        "agentic_intermediate_failure_recovery_rate": sum(
            row["agentic"]["status"] == "completed" for row in recoverable_failures
        )
        / len(recoverable_failures),
        "completed_observation_reuse_rate": sum(
            row["agentic"]["retrieval_reused"] for row in rows if row["agentic"]["replans"]
        )
        / sum(bool(row["agentic"]["replans"]) for row in rows),
        "unrecoverable_safe_stop_rate": sum(
            row["agentic"]["safe_stop"] for row in unrecoverable
        )
        / len(unrecoverable),
    }
    return {
        "schema_version": 1,
        "experiment": "stage11-multi-step-mid-flight-replanning-v1",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "configuration": {
            "cases": len(cases),
            "reviewed_cases": sum(item.reviewed for item in cases),
        },
        "metrics": metrics,
        "cases": rows,
        "limitations": [
            "Tools and failures are deterministic fixtures, not live provider calls.",
            "The runtime planner is deterministic; a real LLM replanner remains a candidate.",
            "The four labels are project-authored and not independently reviewed.",
        ],
    }
