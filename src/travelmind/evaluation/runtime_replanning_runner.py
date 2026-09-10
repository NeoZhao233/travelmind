from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from travelmind.planner.demo import DemoPlanner
from travelmind.runtime.builder import build_travel_runtime_graph
from travelmind.runtime.models import (
    ExecutionPlan,
    FailureAttribution,
    FailureLayer,
    RuntimeStep,
    StepKind,
    ToolResponse,
)
from travelmind.runtime.tools import DictToolRegistry
from travelmind.schemas import Evidence, TravelRequest


class RuntimeFailureCase(BaseModel):
    case_id: str
    fault: Literal[
        "transient_timeout_once",
        "permanent_booking_failure",
        "invalid_tool_output",
        "persistent_permanent_failure",
    ]
    recoverable: bool
    expected_status: Literal["completed", "failed"]
    expected_replans: int
    expected_layer: FailureLayer
    reviewed: bool


class _FailureAwarePlanner:
    def plan(
        self,
        request: TravelRequest,
        *,
        observations: list[Any],
        previous_plan: ExecutionPlan | None,
        failure: FailureAttribution | None,
    ) -> ExecutionPlan:
        del observations
        revision = 1 if previous_plan is None else previous_plan.revision + 1
        fallback = failure is not None
        kind = StepKind.CHECK_AVAILABILITY if fallback else StepKind.CHECK_BOOKING
        return ExecutionPlan(
            plan_id="controlled-runtime",
            revision=revision,
            goal=request.query,
            reason=(
                f"Replace failed booking path after {failure.reason_code}."
                if failure
                else "Check booking before itinerary generation."
            ),
            steps=[
                RuntimeStep(
                    step_id=f"{kind.value}_r{revision}",
                    kind=kind,
                    tool_name="availability" if fallback else "booking",
                    arguments={"place_id": "forbidden-city"},
                )
            ],
        )


def _seed_evidence() -> Evidence:
    return Evidence(
        id="forbidden-city-static",
        content="故宫官方静态介绍和票价信息。",
        source_url="https://example.com/official",
        source_type="official",
        score=1,
        metadata={"place_id": "forbidden-city", "name": "故宫", "cost": 60},
    )


def _tools(case: RuntimeFailureCase) -> DictToolRegistry:
    calls = {"booking": 0}

    def booking(arguments: dict[str, Any]):
        calls["booking"] += 1
        if case.fault == "transient_timeout_once" and calls["booking"] == 1:
            raise TimeoutError("injected timeout detail")
        if case.fault in {"permanent_booking_failure", "persistent_permanent_failure"}:
            raise PermissionError("injected credential detail")
        if case.fault == "invalid_tool_output":
            return {"outcome": "unsupported"}
        return ToolResponse(
            payload={"place_id": arguments["place_id"], "bookable": True},
            evidence_ids=["booking-live"],
        )

    def availability(arguments: dict[str, Any]):
        if case.fault == "persistent_permanent_failure":
            raise PermissionError("injected fallback credential detail")
        return ToolResponse(
            payload={"place_id": arguments["place_id"], "status": "open"},
            evidence_ids=["availability-live"],
        )

    return DictToolRegistry({"booking": booking, "availability": availability})


def _run(case: RuntimeFailureCase, *, max_replans: int) -> dict[str, Any]:
    graph = build_travel_runtime_graph(
        runtime_planner=_FailureAwarePlanner(),
        tool_registry=_tools(case),
        itinerary_planner=DemoPlanner(),
        max_replans=max_replans,
    )
    result = graph.invoke(
        {
            "request": TravelRequest(query="规划北京一日游"),
            "evidence": [_seed_evidence()],
        }
    )
    failure = result.get("failure_history", [])
    failed_observations = [
        item for item in result.get("observations", []) if item.outcome != "success"
    ]
    observed_layer = failure[0].primary_layer.value if failure else None
    if observed_layer is None and failed_observations:
        observed_layer = FailureLayer.TOOL.value
    return {
        "status": result["status"],
        "replans": result["replan_count"],
        "tool_calls": result["tool_call_count"],
        "observed_layer": observed_layer,
        "plan_revisions": [plan.revision for plan in result["plan_history"]],
        "safe_stop": result["status"] == "failed" and result.get("itinerary") is None,
    }


def _load_cases(path: Path) -> list[RuntimeFailureCase]:
    return [
        RuntimeFailureCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_runtime_replanning_experiment(root: Path) -> dict[str, Any]:
    dataset = root.resolve() / "evals/datasets/runtime_failure_seed.jsonl"
    cases = _load_cases(dataset)
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("runtime failure case IDs must be unique")
    rows = []
    for case in cases:
        baseline = _run(case, max_replans=0)
        agentic = _run(case, max_replans=1)
        rows.append(
            {
                "case_id": case.case_id,
                "fault": case.fault,
                "recoverable": case.recoverable,
                "expected_status": case.expected_status,
                "expected_replans": case.expected_replans,
                "expected_layer": case.expected_layer.value,
                "baseline": baseline,
                "agentic": agentic,
            }
        )

    recoverable = [row for row in rows if row["recoverable"]]
    unrecoverable = [row for row in rows if not row["recoverable"]]
    return {
        "schema_version": 1,
        "experiment": "stage11-controlled-runtime-replanning-v1",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "configuration": {
            "cases": len(cases),
            "reviewed_cases": sum(case.reviewed for case in cases),
            "max_replans": 1,
            "max_tool_attempts": 2,
        },
        "baseline_metrics": {
            "recoverable_completion_rate": sum(
                row["baseline"]["status"] == "completed" for row in recoverable
            )
            / len(recoverable),
        },
        "agentic_metrics": {
            "recoverable_completion_rate": sum(
                row["agentic"]["status"] == "completed" for row in recoverable
            )
            / len(recoverable),
            "expected_replan_rate": sum(
                row["agentic"]["replans"] == row["expected_replans"] for row in rows
            )
            / len(rows),
            "failure_attribution_accuracy": sum(
                row["agentic"]["observed_layer"] == row["expected_layer"]
                for row in rows
            )
            / len(rows),
            "unrecoverable_safe_stop_rate": sum(
                row["agentic"]["safe_stop"] for row in unrecoverable
            )
            / len(unrecoverable),
            "mean_tool_calls": sum(row["agentic"]["tool_calls"] for row in rows) / len(rows),
        },
        "cases": rows,
        "limitations": [
            "Faults and tool results are deterministic injections, not live provider incidents.",
            "The four project-authored cases are not independently reviewed.",
            "This experiment isolates runtime control and does not measure itinerary quality.",
        ],
    }
