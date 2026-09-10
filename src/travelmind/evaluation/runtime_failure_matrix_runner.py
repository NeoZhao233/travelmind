from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from travelmind.runtime.builder import build_travel_runtime_graph
from travelmind.runtime.models import ToolResponse
from travelmind.runtime.policies import DeterministicMultiStepRuntimePlanner
from travelmind.runtime.tools import DictToolRegistry
from travelmind.schemas import Activity, DayPlan, Evidence, Itinerary, TravelRequest


class InjectedFault(BaseModel):
    tool_name: Literal["candidate_search", "availability", "booking", "travel_time"]
    place_id: Literal["forbidden-city", "national-museum"] | None = None
    occurrence: int = Field(ge=1)
    mode: Literal[
        "timeout",
        "connection",
        "permission",
        "runtime",
        "invalid_output",
        "insufficient_evidence",
    ]


class RuntimeFailureMatrixCase(BaseModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    faults: list[InjectedFault]
    requires_replan: bool
    recoverable: bool
    expected_status: Literal["completed", "failed"]
    expected_replans: int = Field(ge=0)
    expected_tool_calls: int = Field(ge=1)
    expected_final_place: Literal["forbidden-city", "national-museum"] | None
    reviewed: bool = False


class _ObservationPlanner:
    def generate(self, request: TravelRequest, evidence: list[Evidence]) -> Itinerary:
        del request
        available = [item for item in evidence if item.metadata.get("status") == "open"]
        selected = available[-1]
        start = datetime(2026, 10, 1, 9, tzinfo=UTC)
        place_id = str(selected.metadata["place_id"])
        cost = 60 if place_id == "forbidden-city" else 0
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
                            estimated_cost=cost,
                            evidence_ids=[selected.id],
                        )
                    ],
                )
            ],
            estimated_total_cost=cost,
            assumptions=["Selected from successful availability observations."],
        )


class _MatrixTools:
    def __init__(self, case: RuntimeFailureMatrixCase) -> None:
        self.case = case
        self.calls = Counter(
            {"candidate_search": 0, "availability": 0, "booking": 0, "travel_time": 0}
        )
        self._target_occurrences: Counter[tuple[str, str | None]] = Counter()
        self.candidate_search_succeeded = False

    def registry(self) -> DictToolRegistry:
        return DictToolRegistry(
            {
                "candidate_search": self.candidate_search,
                "availability": self.availability,
                "booking": self.booking,
                "travel_time": self.travel_time,
            }
        )

    def _fault(self, tool_name: str, place_id: str | None) -> str | None:
        key = (tool_name, place_id)
        self._target_occurrences[key] += 1
        occurrence = self._target_occurrences[key]
        match = next(
            (
                fault
                for fault in self.case.faults
                if fault.tool_name == tool_name
                and fault.place_id == place_id
                and fault.occurrence == occurrence
            ),
            None,
        )
        return match.mode if match is not None else None

    @staticmethod
    def _raise(mode: str | None) -> None:
        if mode == "timeout":
            raise TimeoutError("injected secret timeout detail")
        if mode == "connection":
            raise ConnectionError("injected secret connection detail")
        if mode == "permission":
            raise PermissionError("injected secret permission detail")
        if mode == "runtime":
            raise RuntimeError("injected secret runtime detail")

    def candidate_search(self, arguments: dict[str, Any]) -> ToolResponse:
        del arguments
        self.calls["candidate_search"] += 1
        mode = self._fault("candidate_search", None)
        self._raise(mode)
        if mode == "invalid_output":
            return ToolResponse(payload={}, evidence_ids=[])
        if mode == "insufficient_evidence":
            return ToolResponse(payload={"evidence_count": 0}, evidence_ids=["empty-live"])
        self.candidate_search_succeeded = True
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
        mode = self._fault("availability", place_id)
        self._raise(mode)
        if mode == "invalid_output":
            return ToolResponse(payload={"place_id": place_id}, evidence_ids=["invalid-live"])
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
        place_id = str(arguments["place_id"])
        mode = self._fault("booking", place_id)
        self._raise(mode)
        if mode == "invalid_output":
            return ToolResponse(payload={"place_id": place_id}, evidence_ids=["invalid-live"])
        return ToolResponse(
            payload={"place_id": place_id, "bookable": True},
            evidence_ids=[f"{place_id}-booking-live"],
        )

    def travel_time(self, arguments: dict[str, Any]) -> ToolResponse:
        self.calls["travel_time"] += 1
        destination = str(arguments["destination_place_id"])
        mode = self._fault("travel_time", destination)
        self._raise(mode)
        if mode == "invalid_output":
            return ToolResponse(
                payload={"destination_place_id": destination}, evidence_ids=["invalid-live"]
            )
        return ToolResponse(
            payload={
                "origin_place_id": arguments["origin_place_id"],
                "destination_place_id": destination,
                "duration_minutes": 35,
            },
            evidence_ids=[f"hotel-{destination}-travel-live"],
        )


def load_runtime_failure_matrix(path: Path) -> list[RuntimeFailureMatrixCase]:
    cases = [
        RuntimeFailureMatrixCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("runtime failure matrix case IDs must be unique")
    return cases


def _run_case(case: RuntimeFailureMatrixCase, *, max_replans: int) -> dict[str, Any]:
    tools = _MatrixTools(case)
    graph = build_travel_runtime_graph(
        runtime_planner=DeterministicMultiStepRuntimePlanner(
            origin_place_id="hotel",
            primary_place_id="forbidden-city",
            fallback_place_id="national-museum",
        ),
        tool_registry=tools.registry(),
        itinerary_planner=_ObservationPlanner(),
        max_replans=max_replans,
        max_tool_attempts=2,
        max_tool_calls=12,
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
        "tool_calls": result["tool_call_count"],
        "calls_by_tool": dict(tools.calls),
        "candidate_search_reused": tools.calls["candidate_search"] == 1,
        "candidate_search_succeeded": tools.candidate_search_succeeded,
        "final_place": final_place,
        "safe_stop": result["status"] == "failed" and itinerary is None,
        "outcomes": [
            event["outcome"] for event in result["trajectory"] if event["node"] == "execute"
        ],
        "trajectory": result["trajectory"],
    }


def run_runtime_failure_matrix_experiment(root: Path) -> dict[str, Any]:
    dataset = root.resolve() / "evals/datasets/runtime_failure_matrix_v2.jsonl"
    cases = load_runtime_failure_matrix(dataset)
    rows = []
    for case in cases:
        baseline = _run_case(case, max_replans=0)
        agentic = _run_case(case, max_replans=1)
        rows.append({**case.model_dump(mode="json"), "baseline": baseline, "agentic": agentic})

    replan_cases = [row for row in rows if row["requires_replan"] and row["recoverable"]]
    retry_cases = [
        row for row in rows if not row["requires_replan"] and row["faults"] and row["recoverable"]
    ]
    unrecoverable = [row for row in rows if not row["recoverable"]]
    revised = [
        row
        for row in rows
        if row["agentic"]["replans"] and row["agentic"]["candidate_search_succeeded"]
    ]
    contract_passes = [
        row["agentic"]["status"] == row["expected_status"]
        and row["agentic"]["replans"] == row["expected_replans"]
        and row["agentic"]["tool_calls"] == row["expected_tool_calls"]
        and row["agentic"]["final_place"] == row["expected_final_place"]
        for row in rows
    ]
    mode_counts = Counter(fault["mode"] for row in rows for fault in row["faults"])
    return {
        "schema_version": 1,
        "experiment": "stage12-runtime-failure-matrix-v2",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "configuration": {
            "cases": len(cases),
            "reviewed_cases": sum(case.reviewed for case in cases),
            "failure_mode_counts": dict(mode_counts),
            "max_tool_attempts": 2,
            "max_replans": 1,
        },
        "metrics": {
            "case_contract_pass_rate": sum(contract_passes) / len(contract_passes),
            "baseline_replan_required_recovery_rate": sum(
                row["baseline"]["status"] == "completed" for row in replan_cases
            )
            / len(replan_cases),
            "agentic_replan_required_recovery_rate": sum(
                row["agentic"]["status"] == "completed" for row in replan_cases
            )
            / len(replan_cases),
            "transient_retry_recovery_rate": sum(
                row["agentic"]["status"] == "completed" for row in retry_cases
            )
            / len(retry_cases),
            "completed_observation_reuse_rate": sum(
                row["agentic"]["candidate_search_reused"] for row in revised
            )
            / len(revised),
            "unrecoverable_safe_stop_rate": sum(
                row["agentic"]["safe_stop"] for row in unrecoverable
            )
            / len(unrecoverable),
        },
        "cases": rows,
        "limitations": [
            "The matrix is project-authored and has no independent human review.",
            "Deterministic fixture tools validate control flow, not live provider reliability.",
            "Failure-rate metrics describe this matrix and are not production incident rates.",
        ],
    }
