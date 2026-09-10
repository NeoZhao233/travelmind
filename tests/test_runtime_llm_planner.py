from typing import Any

from travelmind.agentic.llm_provider import StructuredLLMResult
from travelmind.runtime.llm_planner import LLMRuntimePlanner, RuntimePlannerTelemetry
from travelmind.runtime.models import ExecutionPlan, FailureAttribution, FailureLayer
from travelmind.runtime.policies import DeterministicMultiStepRuntimePlanner
from travelmind.schemas import TravelRequest


class FakeProvider:
    def __init__(self, output: dict[str, Any] | Exception) -> None:
        self.output = output
        self.last_user_prompt = ""

    def complete_json(self, **kwargs: Any) -> StructuredLLMResult:
        self.last_user_prompt = kwargs["user_prompt"]
        if isinstance(self.output, Exception):
            raise self.output
        return StructuredLLMResult(
            data=self.output,
            model="fake-deepseek",
            latency_ms=15,
            provider_attempts=1,
        )


def _fallback() -> DeterministicMultiStepRuntimePlanner:
    return DeterministicMultiStepRuntimePlanner(
        origin_place_id="hotel",
        primary_place_id="forbidden-city",
        fallback_place_id="national-museum",
    )


def _valid_initial_output() -> dict[str, Any]:
    return {
        "reason": "Collect evidence before planning.",
        "steps": [
            {
                "step_id": "search_candidates",
                "kind": "retrieve",
                "tool_name": "candidate_search",
                "arguments": {"query": "规划北京历史文化一日游"},
                "depends_on": [],
            },
            {
                "step_id": "check_availability",
                "kind": "check_availability",
                "tool_name": "availability",
                "arguments": {"place_id": "forbidden-city"},
                "depends_on": ["search_candidates"],
            },
            {
                "step_id": "check_travel",
                "kind": "estimate_travel_time",
                "tool_name": "travel_time",
                "arguments": {
                    "origin_place_id": "hotel",
                    "destination_place_id": "forbidden-city",
                },
                "depends_on": ["check_availability"],
            },
        ],
    }


def _planner(provider: FakeProvider, telemetry: RuntimePlannerTelemetry | None = None):
    return LLMRuntimePlanner(
        provider,
        _fallback(),
        allowed_place_ids={"forbidden-city", "national-museum"},
        origin_place_id="hotel",
        primary_place_id="forbidden-city",
        fallback_place_id="national-museum",
        telemetry=telemetry,
    )


def test_llm_runtime_planner_accepts_typed_allowlisted_plan() -> None:
    telemetry = RuntimePlannerTelemetry()
    provider = FakeProvider(_valid_initial_output())
    request = TravelRequest(query="规划北京历史文化一日游")

    plan = _planner(provider, telemetry).plan(
        request,
        observations=[],
        previous_plan=None,
        failure=None,
    )

    assert plan.revision == 1
    assert plan.goal == request.query
    assert [step.tool_name for step in plan.steps] == [
        "candidate_search",
        "availability",
        "travel_time",
    ]
    assert telemetry.calls[0].candidate_success is True
    assert telemetry.calls[0].fallback_used is False


def test_llm_runtime_planner_rejects_unknown_place_and_uses_fallback() -> None:
    telemetry = RuntimePlannerTelemetry()
    output = _valid_initial_output()
    output["steps"][1]["arguments"] = {"place_id": "invented-place"}

    plan = _planner(FakeProvider(output), telemetry).plan(
        TravelRequest(query="规划北京历史文化一日游"),
        observations=[],
        previous_plan=None,
        failure=None,
    )

    assert plan.plan_id == "multi-step-beijing-day-trip"
    assert telemetry.calls[0].candidate_success is False
    assert telemetry.calls[0].fallback_used is True
    assert telemetry.calls[0].error_type == "RuntimePlanValidationError"
    assert telemetry.calls[0].reason_code == "PLACE_NOT_ALLOWLISTED"
    assert telemetry.calls[0].model == "fake-deepseek"


def test_llm_runtime_planner_rejects_tool_kind_mismatch() -> None:
    output = _valid_initial_output()
    output["steps"][0]["tool_name"] = "booking"
    telemetry = RuntimePlannerTelemetry()

    _planner(FakeProvider(output), telemetry).plan(
        TravelRequest(query="规划北京历史文化一日游"),
        observations=[],
        previous_plan=None,
        failure=None,
    )

    assert telemetry.calls[0].candidate_success is False
    assert telemetry.calls[0].error_type == "RuntimePlanValidationError"
    assert telemetry.calls[0].reason_code == "TOOL_KIND_MISMATCH"


def test_runtime_canonicalizes_but_counts_model_supplied_extra_arguments() -> None:
    output = _valid_initial_output()
    output["steps"][0]["arguments"] = {
        "query": "model rewrite",
        "interests": ["history"],
    }
    output["steps"][1]["arguments"] = {
        "place_id": "forbidden-city",
        "date": "today",
    }
    telemetry = RuntimePlannerTelemetry()

    plan = _planner(FakeProvider(output), telemetry).plan(
        TravelRequest(query="规划北京历史文化一日游"),
        observations=[],
        previous_plan=None,
        failure=None,
    )

    assert plan.steps[0].arguments == {"query": "规划北京历史文化一日游"}
    assert plan.steps[1].arguments == {"place_id": "forbidden-city"}
    assert telemetry.calls[0].candidate_success is True
    assert telemetry.calls[0].normalized_step_count == 2


def test_llm_runtime_planner_provider_failure_is_sanitized_and_falls_back() -> None:
    telemetry = RuntimePlannerTelemetry()
    provider = FakeProvider(RuntimeError("secret provider response"))

    plan = _planner(provider, telemetry).plan(
        TravelRequest(query="规划北京历史文化一日游"),
        observations=[],
        previous_plan=None,
        failure=None,
    )

    assert plan.revision == 1
    assert telemetry.calls[0].error_type == "RuntimeError"
    assert telemetry.calls[0].reason_code == "PROVIDER_OR_ENVELOPE_FAILED"
    assert "secret provider response" not in str(telemetry.calls)


def test_llm_runtime_replan_keeps_runtime_owned_goal_and_revision() -> None:
    output = {
        "reason": "Use the alternative after failure.",
        "steps": [
            {
                "step_id": "fallback_availability",
                "kind": "check_availability",
                "tool_name": "availability",
                "arguments": {"place_id": "national-museum"},
                "depends_on": [],
            }
        ],
    }
    previous = ExecutionPlan(
        plan_id="stable-plan",
        revision=1,
        goal="original user goal",
        reason="initial",
        steps=_fallback()._place_checks("forbidden-city", suffix="primary"),
    )

    plan = _planner(FakeProvider(output)).plan(
        TravelRequest(query="a different request string"),
        observations=[],
        previous_plan=previous,
        failure=FailureAttribution(
            primary_layer=FailureLayer.TOOL,
            reason_code="PERMANENT_ERROR",
        ),
    )

    assert plan.plan_id == "stable-plan"
    assert plan.revision == 2
    assert plan.goal == "original user goal"
