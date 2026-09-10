from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from travelmind.planner.base import Planner
from travelmind.planner.constraints import validate_itinerary
from travelmind.runtime.grounding import validate_grounding
from travelmind.runtime.models import (
    ExecutionPlan,
    FailureAttribution,
    FailureLayer,
    StepKind,
    StepStatus,
    ToolObservation,
    ToolOutcome,
    ToolResponse,
)
from travelmind.runtime.protocols import RuntimePlanner, ToolRegistry
from travelmind.runtime.state import TravelRuntimeState
from travelmind.schemas import Evidence


class ToolOutputValidationError(ValueError):
    """The tool returned data that does not satisfy its step-specific contract."""


class InsufficientEvidenceError(ValueError):
    """Retrieval completed but produced no admissible evidence."""


def _validate_tool_response(step_kind: StepKind, response: ToolResponse) -> None:
    if response.outcome != ToolOutcome.SUCCESS:
        return
    required_fields: dict[StepKind, tuple[str, ...]] = {
        StepKind.RETRIEVE: ("evidence_count",),
        StepKind.CHECK_AVAILABILITY: ("place_id", "status"),
        StepKind.CHECK_BOOKING: ("place_id", "bookable"),
        StepKind.ESTIMATE_TRAVEL_TIME: (
            "origin_place_id",
            "destination_place_id",
            "duration_minutes",
        ),
    }
    missing = [field for field in required_fields[step_kind] if field not in response.payload]
    if missing:
        raise ToolOutputValidationError("successful tool response is missing required fields")
    if step_kind == StepKind.RETRIEVE:
        count = response.payload["evidence_count"]
        if not isinstance(count, int):
            raise ToolOutputValidationError("evidence_count must be an integer")
        if count < 1:
            raise InsufficientEvidenceError("retrieval returned no admissible evidence")
    if not response.evidence_ids:
        raise ToolOutputValidationError("successful tool response requires evidence_ids")


def _tool_evidence(observations: list[ToolObservation]) -> list[Evidence]:
    """Convert only successful typed observations into planner-visible realtime evidence."""

    converted: list[Evidence] = []
    for observation in observations:
        if observation.outcome != ToolOutcome.SUCCESS:
            continue
        for identity in observation.evidence_ids:
            converted.append(
                Evidence(
                    id=identity,
                    content=json.dumps(observation.payload, ensure_ascii=False, sort_keys=True),
                    source_url=f"tool://{observation.tool_name}",
                    source_type="realtime",
                    score=1.0,
                    retrieved_at=observation.observed_at,
                    metadata={
                        **observation.payload,
                        "tool_name": observation.tool_name,
                        "valid_until": (
                            observation.valid_until.isoformat()
                            if observation.valid_until is not None
                            else None
                        ),
                    },
                )
            )
    return converted


def build_travel_runtime_graph(
    *,
    runtime_planner: RuntimePlanner,
    tool_registry: ToolRegistry,
    itinerary_planner: Planner,
    max_replans: int = 2,
    max_tool_attempts: int = 2,
    max_tool_calls: int = 12,
):
    """Build a bounded Plan-Act-Observe-Replan graph with typed failure attribution."""

    if max_replans < 0 or max_tool_attempts < 1 or max_tool_calls < 1:
        raise ValueError("runtime budgets must be non-negative and tool budgets positive")

    def trace(state: TravelRuntimeState, node: str, outcome: str, **details: object):
        return [*state.get("trajectory", []), {"node": node, "outcome": outcome, **details}]

    def add_failure(
        state: TravelRuntimeState,
        failure: FailureAttribution,
    ) -> dict[str, object]:
        return {
            "current_failure": failure,
            "failure_history": [*state.get("failure_history", []), failure],
        }

    def initialize(state: TravelRuntimeState) -> TravelRuntimeState:
        return {
            "evidence": state.get("evidence", []),
            "plan_history": [],
            "observations": [],
            "failure_history": [],
            "grounding_issues": [],
            "violations": [],
            "replan_count": 0,
            "tool_call_count": 0,
            "trajectory": [{"node": "initialize", "outcome": "initialized"}],
            "status": "initialized",
            "failure_reason": None,
        }

    def plan(state: TravelRuntimeState) -> TravelRuntimeState:
        previous = state.get("current_plan")
        try:
            candidate = runtime_planner.plan(
                state["request"],
                observations=state.get("observations", []),
                previous_plan=previous,
                failure=state.get("current_failure"),
            )
            expected_revision = 1 if previous is None else previous.revision + 1
            if candidate.revision != expected_revision:
                raise ValueError("planner returned a non-monotonic plan revision")
        except Exception as exc:
            failure = FailureAttribution(
                primary_layer=FailureLayer.ORCHESTRATION,
                reason_code="PLAN_CREATION_FAILED",
                contributing_reason_codes=[type(exc).__name__],
            )
            return {
                **add_failure(state, failure),
                "status": "failed",
                "failure_reason": "Unable to create a valid bounded execution plan.",
                "trajectory": trace(
                    state, "plan", "failed", error_type=type(exc).__name__
                ),
            }
        is_replan = previous is not None
        return {
            "current_plan": candidate,
            "plan_history": [*state.get("plan_history", []), candidate],
            "replan_count": state.get("replan_count", 0) + int(is_replan),
            "current_failure": None,
            "status": "planning",
            "trajectory": trace(
                state,
                "replan" if is_replan else "plan",
                "created",
                revision=candidate.revision,
                step_count=len(candidate.steps),
            ),
        }

    def route_after_plan(state: TravelRuntimeState) -> str:
        return "fail" if state["status"] == "failed" else "execute"

    def _ready_step(plan_value: ExecutionPlan):
        completed = {
            step.step_id for step in plan_value.steps if step.status == StepStatus.COMPLETED
        }
        return next(
            (
                step
                for step in plan_value.steps
                if step.status == StepStatus.PENDING and set(step.depends_on).issubset(completed)
            ),
            None,
        )

    def execute(state: TravelRuntimeState) -> TravelRuntimeState:
        current = state["current_plan"].model_copy(deep=True)
        step = _ready_step(current)
        if step is None:
            failure = FailureAttribution(
                primary_layer=FailureLayer.ORCHESTRATION,
                reason_code="NO_READY_STEP",
            )
            return {
                **add_failure(state, failure),
                "current_plan": current,
                "status": "executing",
                "trajectory": trace(state, "execute", "blocked"),
            }
        if state.get("tool_call_count", 0) >= max_tool_calls:
            failure = FailureAttribution(
                primary_layer=FailureLayer.ORCHESTRATION,
                reason_code="TOOL_CALL_BUDGET_EXHAUSTED",
                related_step_id=step.step_id,
                related_tool=step.tool_name,
            )
            step.status = StepStatus.FAILED
            step.outcome_code = failure.reason_code
            return {
                **add_failure(state, failure),
                "current_plan": current,
                "status": "executing",
                "trajectory": trace(state, "execute", "budget_exhausted"),
            }

        step.attempts += 1
        call_id = f"{step.step_id}:{step.attempts}:{uuid4().hex[:8]}"
        outcome = ToolOutcome.SUCCESS
        payload: dict[str, Any] = {}
        evidence_ids: list[str] = []
        valid_until = None
        error_type = None
        try:
            tool = tool_registry.get(step.tool_name)
            raw_response = tool(step.arguments)
            response = (
                raw_response
                if isinstance(raw_response, ToolResponse)
                else ToolResponse.model_validate(raw_response)
            )
            _validate_tool_response(step.kind, response)
            outcome = response.outcome
            payload = response.payload
            evidence_ids = response.evidence_ids
            valid_until = response.valid_until
        except (TimeoutError, ConnectionError) as exc:
            outcome = ToolOutcome.TRANSIENT_ERROR
            error_type = type(exc).__name__
        except InsufficientEvidenceError as exc:
            outcome = ToolOutcome.INSUFFICIENT_EVIDENCE
            error_type = type(exc).__name__
        except (ValidationError, ToolOutputValidationError) as exc:
            outcome = ToolOutcome.INVALID_OUTPUT
            error_type = type(exc).__name__
        except Exception as exc:
            outcome = ToolOutcome.PERMANENT_ERROR
            error_type = type(exc).__name__

        observation = ToolObservation(
            call_id=call_id,
            step_id=step.step_id,
            tool_name=step.tool_name,
            outcome=outcome,
            payload=payload,
            evidence_ids=evidence_ids,
            error_type=error_type,
            observed_at=datetime.now(UTC),
            valid_until=valid_until,
        )
        updates: dict[str, object] = {
            "current_plan": current,
            "observations": [*state.get("observations", []), observation],
            "tool_call_count": state.get("tool_call_count", 0) + 1,
            "status": "executing",
            "trajectory": trace(
                state,
                "execute",
                outcome.value,
                step_id=step.step_id,
                tool=step.tool_name,
                attempt=step.attempts,
            ),
        }
        if outcome == ToolOutcome.SUCCESS:
            step.status = StepStatus.COMPLETED
            step.outcome_code = "SUCCESS"
            updates["current_failure"] = None
            return updates  # type: ignore[return-value]
        if outcome == ToolOutcome.TRANSIENT_ERROR and step.attempts < max_tool_attempts:
            return updates  # type: ignore[return-value]

        step.status = StepStatus.FAILED
        step.outcome_code = outcome.value.upper()
        layer = FailureLayer.RETRIEVAL if step.kind == StepKind.RETRIEVE else FailureLayer.TOOL
        failure = FailureAttribution(
            primary_layer=layer,
            reason_code=step.outcome_code,
            related_step_id=step.step_id,
            related_tool=step.tool_name,
            contributing_reason_codes=[error_type] if error_type else [],
        )
        updates.update(add_failure(state, failure))
        return updates  # type: ignore[return-value]

    def route_after_execute(state: TravelRuntimeState) -> str:
        current = state["current_plan"]
        if state.get("current_failure") is not None:
            return "replan" if state.get("replan_count", 0) < max_replans else "fail"
        if any(step.status == StepStatus.PENDING for step in current.steps):
            return "execute"
        return "generate"

    def generate(state: TravelRuntimeState) -> TravelRuntimeState:
        try:
            evidence_by_id = {item.id: item for item in state.get("evidence", [])}
            evidence_by_id.update(
                {item.id: item for item in _tool_evidence(state.get("observations", []))}
            )
            planner_evidence = list(evidence_by_id.values())
            itinerary = itinerary_planner.generate(state["request"], planner_evidence)
        except Exception as exc:
            failure = FailureAttribution(
                primary_layer=FailureLayer.GENERATION,
                reason_code="GENERATION_FAILED",
                contributing_reason_codes=[type(exc).__name__],
            )
            return {
                **add_failure(state, failure),
                "status": "generating",
                "trajectory": trace(
                    state, "generate", "failed", error_type=type(exc).__name__
                ),
            }
        return {
            "itinerary": itinerary,
            "current_failure": None,
            "status": "generating",
            "trajectory": trace(state, "generate", "generated"),
        }

    def route_after_generate(state: TravelRuntimeState) -> str:
        if state.get("current_failure") is None:
            return "validate"
        return "replan" if state.get("replan_count", 0) < max_replans else "fail"

    def validate(state: TravelRuntimeState) -> TravelRuntimeState:
        itinerary = state.get("itinerary")
        if itinerary is None:
            failure = FailureAttribution(
                primary_layer=FailureLayer.GENERATION,
                reason_code="MISSING_ITINERARY",
            )
            return {**add_failure(state, failure), "status": "validating"}
        grounding = validate_grounding(
            itinerary, state.get("evidence", []), state.get("observations", [])
        )
        violations = validate_itinerary(itinerary, state["request"].constraints)
        if grounding:
            failure = FailureAttribution(
                primary_layer=FailureLayer.GENERATION,
                reason_code="UNGROUNDED_OUTPUT",
                related_evidence_ids=[
                    issue.evidence_id for issue in grounding if issue.evidence_id is not None
                ],
                contributing_reason_codes=list(dict.fromkeys(issue.code for issue in grounding)),
            )
        elif violations:
            failure = FailureAttribution(
                primary_layer=FailureLayer.VALIDATION,
                reason_code="CONSTRAINT_VIOLATION",
                contributing_reason_codes=list(
                    dict.fromkeys(violation.code for violation in violations)
                ),
            )
        else:
            return {
                "grounding_issues": [],
                "violations": [],
                "status": "completed",
                "failure_reason": None,
                "trajectory": trace(state, "validate", "completed"),
            }
        return {
            **add_failure(state, failure),
            "grounding_issues": grounding,
            "violations": violations,
            "status": "validating",
            "trajectory": trace(
                state, "validate", "rejected", reason_code=failure.reason_code
            ),
        }

    def route_after_validate(state: TravelRuntimeState) -> str:
        if state["status"] == "completed":
            return "complete"
        return "replan" if state.get("replan_count", 0) < max_replans else "fail"

    def fail(state: TravelRuntimeState) -> TravelRuntimeState:
        failure = state.get("current_failure")
        reason_code = failure.reason_code if failure else "UNKNOWN_FAILURE"
        return {
            "status": "failed",
            "failure_reason": f"Runtime stopped safely: {reason_code}.",
            "trajectory": trace(state, "fail", "safe_stop", reason_code=reason_code),
        }

    graph = StateGraph(TravelRuntimeState)
    graph.add_node("initialize", initialize)
    graph.add_node("plan", plan)
    graph.add_node("execute", execute)
    graph.add_node("generate", generate)
    graph.add_node("validate", validate)
    graph.add_node("fail", fail)
    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "plan")
    graph.add_conditional_edges("plan", route_after_plan, {"execute": "execute", "fail": "fail"})
    graph.add_conditional_edges(
        "execute",
        route_after_execute,
        {"execute": "execute", "replan": "plan", "generate": "generate", "fail": "fail"},
    )
    graph.add_conditional_edges(
        "generate", route_after_generate, {"validate": "validate", "replan": "plan", "fail": "fail"}
    )
    graph.add_conditional_edges(
        "validate", route_after_validate, {"complete": END, "replan": "plan", "fail": "fail"}
    )
    graph.add_edge("fail", END)
    return graph.compile()
