from __future__ import annotations

from typing import Any

from travelmind.planner.demo import DemoPlanner
from travelmind.runtime.builder import build_travel_runtime_graph
from travelmind.runtime.models import (
    ExecutionPlan,
    FailureAttribution,
    RuntimeStep,
    StepKind,
    ToolOutcome,
    ToolResponse,
)
from travelmind.runtime.tools import DictToolRegistry
from travelmind.schemas import Evidence, TravelRequest


def _evidence() -> Evidence:
    return Evidence(
        id="forbidden-city-source",
        content="故宫官方信息，包括开放与预约说明。",
        source_url="https://example.com/official",
        source_type="official",
        score=1,
        metadata={"place_id": "forbidden-city", "name": "故宫", "cost": 60},
    )


class FailureAwarePlanner:
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
        if failure is None:
            step = RuntimeStep(
                step_id=f"booking_r{revision}",
                kind=StepKind.CHECK_BOOKING,
                tool_name="booking",
                arguments={"place_id": "forbidden-city"},
            )
            reason = "Check the requested attraction booking status."
        else:
            step = RuntimeStep(
                step_id=f"availability_r{revision}",
                kind=StepKind.CHECK_AVAILABILITY,
                tool_name="availability",
                arguments={"place_id": "forbidden-city", "fallback": True},
            )
            reason = f"Replace failed booking path after {failure.reason_code}."
        return ExecutionPlan(
            plan_id="beijing-runtime",
            revision=revision,
            goal=request.query,
            reason=reason,
            steps=[step],
        )


def _invoke(tools: dict[str, Any], **budgets: int):
    graph = build_travel_runtime_graph(
        runtime_planner=FailureAwarePlanner(),
        tool_registry=DictToolRegistry(tools),
        itinerary_planner=DemoPlanner(),
        **budgets,
    )
    return graph.invoke(
        {"request": TravelRequest(query="规划北京一日游"), "evidence": [_evidence()]}
    )


def test_transient_tool_failure_retries_without_replanning() -> None:
    calls = 0

    def booking(arguments: dict[str, Any]) -> ToolResponse:
        nonlocal calls
        del arguments
        calls += 1
        if calls == 1:
            raise TimeoutError("private downstream detail")
        return ToolResponse(
            payload={"place_id": "forbidden-city", "bookable": True},
            evidence_ids=["booking-live"],
        )

    result = _invoke({"booking": booking, "availability": lambda _: {}})

    assert result["status"] == "completed"
    assert result["replan_count"] == 0
    assert result["tool_call_count"] == 2
    assert [item.outcome for item in result["observations"]] == [
        ToolOutcome.TRANSIENT_ERROR,
        ToolOutcome.SUCCESS,
    ]
    assert "private downstream detail" not in str(result)


def test_permanent_tool_failure_creates_new_plan_revision() -> None:
    def booking(arguments: dict[str, Any]) -> ToolResponse:
        del arguments
        raise PermissionError("credential content must not enter state")

    result = _invoke(
        {
            "booking": booking,
            "availability": lambda arguments: ToolResponse(
                payload={
                    "kind": StepKind.CHECK_AVAILABILITY,
                    "place_id": arguments["place_id"],
                    "status": "open",
                },
                evidence_ids=["availability-live"],
            ),
        }
    )

    assert result["status"] == "completed"
    assert result["replan_count"] == 1
    assert [plan.revision for plan in result["plan_history"]] == [1, 2]
    assert result["plan_history"][1].steps[0].tool_name == "availability"
    assert result["failure_history"][0].primary_layer == "tool"
    assert result["failure_history"][0].reason_code == "PERMANENT_ERROR"
    assert "credential content" not in str(result)


def test_invalid_tool_schema_is_distinct_from_transport_failure() -> None:
    result = _invoke(
        {
            "booking": lambda _: {"outcome": "not-a-supported-outcome"},
            "availability": lambda _: ToolResponse(
                payload={"place_id": "forbidden-city", "status": "open"},
                evidence_ids=["availability-live"],
            ),
        }
    )

    assert result["status"] == "completed"
    first = result["failure_history"][0]
    assert first.primary_layer == "tool"
    assert first.reason_code == "INVALID_OUTPUT"
    assert first.contributing_reason_codes == ["ValidationError"]


def test_replan_budget_exhaustion_fails_closed() -> None:
    def unavailable(arguments: dict[str, Any]) -> ToolResponse:
        del arguments
        return ToolResponse(outcome=ToolOutcome.PERMANENT_ERROR)

    result = _invoke(
        {"booking": unavailable, "availability": unavailable},
        max_replans=1,
    )

    assert result["status"] == "failed"
    assert result["replan_count"] == 1
    assert len(result["plan_history"]) == 2
    assert result["failure_reason"] == "Runtime stopped safely: PERMANENT_ERROR."


def test_retrieval_step_failure_is_attributed_to_retrieval_layer() -> None:
    class RetrievalPlanner(FailureAwarePlanner):
        def plan(self, request: TravelRequest, **kwargs: Any) -> ExecutionPlan:
            del kwargs
            return ExecutionPlan(
                plan_id="retrieval",
                revision=1,
                goal=request.query,
                reason="Retrieve missing evidence.",
                steps=[
                    RuntimeStep(
                        step_id="retrieve_once",
                        kind=StepKind.RETRIEVE,
                        tool_name="retriever",
                    )
                ],
            )

    graph = build_travel_runtime_graph(
        runtime_planner=RetrievalPlanner(),
        tool_registry=DictToolRegistry({"retriever": lambda _: (_ for _ in ()).throw(OSError())}),
        itinerary_planner=DemoPlanner(),
        max_replans=0,
    )
    result = graph.invoke({"request": TravelRequest(query="北京"), "evidence": [_evidence()]})

    assert result["status"] == "failed"
    assert result["current_failure"].primary_layer == "retrieval"


def test_empty_retrieval_is_not_mislabeled_as_generation_failure() -> None:
    class RetrievalPlanner(FailureAwarePlanner):
        def plan(self, request: TravelRequest, **kwargs: Any) -> ExecutionPlan:
            del kwargs
            return ExecutionPlan(
                plan_id="empty-retrieval",
                revision=1,
                goal=request.query,
                reason="Retrieve missing evidence.",
                steps=[
                    RuntimeStep(
                        step_id="retrieve_empty",
                        kind=StepKind.RETRIEVE,
                        tool_name="retriever",
                    )
                ],
            )

    graph = build_travel_runtime_graph(
        runtime_planner=RetrievalPlanner(),
        tool_registry=DictToolRegistry(
            {"retriever": lambda _: ToolResponse(payload={"evidence_count": 0})}
        ),
        itinerary_planner=DemoPlanner(),
        max_replans=0,
    )
    result = graph.invoke({"request": TravelRequest(query="不存在的景点")})

    assert result["status"] == "failed"
    assert result["current_failure"].primary_layer == "retrieval"
    assert result["current_failure"].reason_code == "INSUFFICIENT_EVIDENCE"


def test_runtime_plan_rejects_forward_dependency() -> None:
    try:
        ExecutionPlan(
            plan_id="invalid",
            revision=1,
            goal="test",
            reason="test invalid dependency",
            steps=[
                RuntimeStep(
                    step_id="first",
                    kind=StepKind.CHECK_BOOKING,
                    tool_name="booking",
                    depends_on=["later"],
                ),
                RuntimeStep(
                    step_id="later",
                    kind=StepKind.CHECK_AVAILABILITY,
                    tool_name="availability",
                ),
            ],
        )
    except ValueError as exc:
        assert "dependencies must reference earlier steps" in str(exc)
    else:
        raise AssertionError("Expected invalid execution plan to fail")


def test_successful_tool_observation_is_visible_to_itinerary_planner() -> None:
    class CapturingPlanner(DemoPlanner):
        def __init__(self) -> None:
            self.seen_ids: list[str] = []

        def generate(self, request: TravelRequest, evidence: list[Evidence]):
            self.seen_ids = [item.id for item in evidence]
            return super().generate(request, evidence[:1])

    planner = CapturingPlanner()
    graph = build_travel_runtime_graph(
        runtime_planner=FailureAwarePlanner(),
        tool_registry=DictToolRegistry(
            {
                "booking": lambda _: ToolResponse(
                    payload={"place_id": "forbidden-city", "bookable": True},
                    evidence_ids=["booking-live"],
                ),
                "availability": lambda _: {},
            }
        ),
        itinerary_planner=planner,
    )

    result = graph.invoke(
        {"request": TravelRequest(query="规划北京一日游"), "evidence": [_evidence()]}
    )

    assert result["status"] == "completed"
    assert planner.seen_ids == ["forbidden-city-source", "booking-live"]
