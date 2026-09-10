from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from travelmind.planner.constraints import validate_itinerary
from travelmind.repair.deterministic import DeterministicDayRepairer
from travelmind.repair.models import (
    RepairRequest,
    RepairTrajectoryEvent,
)
from travelmind.repair.protocols import ItineraryRepairer
from travelmind.repair.state import RepairState

_REPAIRABLE_CODES = {
    "COST_TOTAL_MISMATCH",
    "BUDGET_EXCEEDED",
    "REQUIRED_PLACE_MISSING",
    "EXCLUDED_PLACE_PRESENT",
    "TIME_CONFLICT",
    "ACTIVITY_EVIDENCE_MISSING",
    "AVAILABILITY_MISSING",
    "AVAILABILITY_UNKNOWN",
    "AVAILABILITY_STALE",
    "PLACE_CLOSED",
    "OUTSIDE_OPENING_HOURS",
    "BOOKING_UNCONFIRMED",
    "DAY_WINDOW_VIOLATION",
    "TRAVEL_TIME_MISSING",
    "TRAVEL_TIME_UNKNOWN",
    "TRAVEL_TIME_STALE",
    "TRAVEL_TIME_INFEASIBLE",
}


def build_itinerary_repair_graph(
    *,
    repairer: ItineraryRepairer | None = None,
    max_repair_attempts: int = 2,
):
    """Build a bounded validate-repair-revalidate loop with deterministic fallback."""

    if max_repair_attempts < 1:
        raise ValueError("max_repair_attempts must be positive")
    primary = repairer or DeterministicDayRepairer()
    fallback = DeterministicDayRepairer()

    def event(
        state: RepairState,
        *,
        node: str,
        outcome: str,
        violations: list[str] | None = None,
        modified_days: list[int] | None = None,
        error_type: str | None = None,
        attempt: int | None = None,
    ) -> list[RepairTrajectoryEvent]:
        return [
            *state.get("trajectory", []),
            RepairTrajectoryEvent(
                node=node,
                attempt=(state.get("repair_attempts", 0) if attempt is None else attempt),
                outcome=outcome,
                violation_codes=violations or [],
                modified_days=modified_days or [],
                error_type=error_type,
            ),
        ]

    def initialize(_: RepairState) -> RepairState:
        return {
            "violations": [],
            "repair_attempts": 0,
            "modified_days": [],
            "trajectory": [
                RepairTrajectoryEvent(node="initialize", attempt=0, outcome="initialized")
            ],
            "degraded_components": [],
            "dependency_errors": [],
            "status": "initialized",
            "failure_reason": None,
        }

    def validate(state: RepairState) -> RepairState:
        violations = validate_itinerary(state["itinerary"], state["constraints"], state["context"])
        return {
            "violations": violations,
            "status": "completed" if not violations else "validating",
            "failure_reason": None,
            "trajectory": event(
                state,
                node="validate",
                outcome="valid" if not violations else "violations_found",
                violations=sorted({item.code for item in violations}),
            ),
        }

    def route_after_validation(state: RepairState) -> str:
        if not state["violations"]:
            return "complete"
        if not any(item.code in _REPAIRABLE_CODES for item in state["violations"]):
            return "fail"
        if state["repair_attempts"] < max_repair_attempts:
            return "repair"
        return "fail"

    def repair(state: RepairState) -> RepairState:
        attempt = state["repair_attempts"] + 1
        request = RepairRequest(
            itinerary=state["itinerary"],
            constraints=state["constraints"],
            context=state["context"],
            candidates=state.get("candidates", []),
            violations=state["violations"],
        )
        try:
            outcome = primary.repair(request)
        except Exception as exc:
            try:
                outcome = fallback.repair(request)
            except Exception as fallback_exc:
                errors = [
                    *state.get("dependency_errors", []),
                    {
                        "component": "itinerary_repairer",
                        "error_type": type(exc).__name__,
                    },
                    {
                        "component": "deterministic_repair_fallback",
                        "error_type": type(fallback_exc).__name__,
                    },
                ]
                return {
                    "repair_attempts": attempt,
                    "dependency_errors": errors,
                    "degraded_components": [
                        *state.get("degraded_components", []),
                        "itinerary_repairer",
                        "deterministic_repair_fallback",
                    ],
                    "status": "repairing",
                    "trajectory": event(
                        state,
                        node="repair",
                        outcome="fallback_failed",
                        error_type=type(fallback_exc).__name__,
                        attempt=attempt,
                    ),
                }
            errors = [
                *state.get("dependency_errors", []),
                {
                    "component": "itinerary_repairer",
                    "error_type": type(exc).__name__,
                },
            ]
            return {
                "itinerary": outcome.itinerary,
                "repair_attempts": attempt,
                "modified_days": sorted(
                    set(state.get("modified_days", [])) | set(outcome.modified_days)
                ),
                "dependency_errors": errors,
                "degraded_components": list(
                    dict.fromkeys([*state.get("degraded_components", []), "itinerary_repairer"])
                ),
                "status": "repairing",
                "trajectory": event(
                    state,
                    node="repair",
                    outcome="fallback",
                    modified_days=outcome.modified_days,
                    error_type=type(exc).__name__,
                    attempt=attempt,
                ),
            }
        return {
            "itinerary": outcome.itinerary,
            "repair_attempts": attempt,
            "modified_days": sorted(
                set(state.get("modified_days", [])) | set(outcome.modified_days)
            ),
            "status": "repairing",
            "trajectory": event(
                state,
                node="repair",
                outcome=outcome.action,
                modified_days=outcome.modified_days,
                attempt=attempt,
            ),
        }

    def fail(state: RepairState) -> RepairState:
        exhausted = state["repair_attempts"] >= max_repair_attempts
        return {
            "status": "failed",
            "failure_reason": (
                "Itinerary remains invalid after bounded local repair."
                if exhausted
                else "No safe local repair strategy exists for the violations."
            ),
            "trajectory": event(
                state,
                node="fallback",
                outcome=("repair_exhausted" if exhausted else "not_locally_repairable"),
                violations=sorted({item.code for item in state["violations"]}),
            ),
        }

    graph = StateGraph(RepairState)
    nodes: dict[str, Callable] = {
        "initialize": initialize,
        "validate": validate,
        "repair": repair,
        "fail": fail,
    }
    for name, node in nodes.items():
        graph.add_node(name, node)
    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validation,
        {"complete": END, "repair": "repair", "fail": "fail"},
    )
    graph.add_edge("repair", "validate")
    graph.add_edge("fail", END)
    return graph.compile()
