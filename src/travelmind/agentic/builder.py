from __future__ import annotations

from collections.abc import Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from travelmind.agentic.models import TrajectoryEvent
from travelmind.agentic.policies import (
    CoverageEvidenceGrader,
    MissingAspectQueryRewriter,
    RuleBasedQueryRouter,
)
from travelmind.agentic.protocols import EvidenceGrader, QueryRewriter, QueryRouter
from travelmind.agentic.state import AgenticTravelState
from travelmind.planner.base import Planner
from travelmind.planner.constraints import validate_itinerary
from travelmind.retrieval.base import Retriever


def build_agentic_travel_graph(
    *,
    retriever: Retriever,
    planner: Planner,
    router: QueryRouter | None = None,
    grader: EvidenceGrader | None = None,
    rewriter: QueryRewriter | None = None,
    max_retrieval_attempts: int = 2,
    retrieval_limit: int = 10,
    checkpointer: BaseCheckpointSaver | None = None,
    interrupt_after: list[str] | None = None,
):
    """Build a bounded Agentic RAG graph with deterministic policy fallbacks."""

    if max_retrieval_attempts < 1:
        raise ValueError("max_retrieval_attempts must be positive")
    if retrieval_limit < 1:
        raise ValueError("retrieval_limit must be positive")
    primary_router = router or RuleBasedQueryRouter()
    primary_grader = grader or CoverageEvidenceGrader()
    primary_rewriter = rewriter or MissingAspectQueryRewriter()
    fallback_router = RuleBasedQueryRouter()
    fallback_grader = CoverageEvidenceGrader()
    fallback_rewriter = MissingAspectQueryRewriter()

    def event(
        state: AgenticTravelState,
        *,
        node: str,
        outcome: str,
        reason_codes: list[str] | None = None,
        error_type: str | None = None,
        attempt: int | None = None,
    ) -> list[TrajectoryEvent]:
        return [
            *state.get("trajectory", []),
            TrajectoryEvent(
                node=node,
                attempt=(state.get("retrieval_attempts", 0) if attempt is None else attempt),
                outcome=outcome,
                reason_codes=reason_codes or [],
                error_type=error_type,
            ),
        ]

    def record_dependency_error(
        state: AgenticTravelState,
        component: str,
        exc: BaseException,
    ) -> tuple[list[str], list[dict[str, str]]]:
        degraded = list(dict.fromkeys([*state.get("degraded_components", []), component]))
        errors = [
            *state.get("dependency_errors", []),
            {"component": component, "error_type": type(exc).__name__},
        ]
        return degraded, errors

    def initialize(state: AgenticTravelState) -> AgenticTravelState:
        return {
            "retrieval_queries": [state["request"].query],
            "evidence": [],
            "violations": [],
            "retrieval_attempts": 0,
            "rewrite_attempts": 0,
            "trajectory": [TrajectoryEvent(node="initialize", attempt=0, outcome="initialized")],
            "degraded_components": [],
            "dependency_errors": [],
            "status": "initialized",
            "failure_reason": None,
        }

    def route_query(state: AgenticTravelState) -> AgenticTravelState:
        try:
            decision = primary_router.route(state["request"])
        except Exception as exc:
            decision = fallback_router.route(state["request"])
            degraded, errors = record_dependency_error(state, "query_router", exc)
            return {
                "routing_decision": decision,
                "degraded_components": degraded,
                "dependency_errors": errors,
                "trajectory": event(
                    state,
                    node="route_query",
                    outcome="fallback",
                    reason_codes=decision.reason_codes,
                    error_type=type(exc).__name__,
                ),
                "status": "routing",
            }
        return {
            "routing_decision": decision,
            "trajectory": event(
                state,
                node="route_query",
                outcome=decision.retrieval_strategy,
                reason_codes=decision.reason_codes,
            ),
            "status": "routing",
        }

    def retrieve(state: AgenticTravelState) -> AgenticTravelState:
        attempt = state["retrieval_attempts"] + 1
        try:
            retrieved = retriever.search(state["retrieval_queries"], limit=retrieval_limit)
        except Exception as exc:
            degraded, errors = record_dependency_error(state, "retriever", exc)
            return {
                "retrieval_attempts": attempt,
                "degraded_components": degraded,
                "dependency_errors": errors,
                "trajectory": event(
                    state,
                    node="retrieve",
                    outcome="error",
                    error_type=type(exc).__name__,
                    attempt=attempt,
                ),
                "status": "retrieving",
            }
        evidence_by_id = {item.id: item for item in state.get("evidence", [])}
        evidence_by_id.update({item.id: item for item in retrieved})
        return {
            "evidence": list(evidence_by_id.values()),
            "retrieval_attempts": attempt,
            "trajectory": event(
                state,
                node="retrieve",
                outcome="success" if retrieved else "empty",
                reason_codes=[f"evidence_count:{len(retrieved)}"],
                attempt=attempt,
            ),
            "status": "retrieving",
        }

    def grade_evidence(state: AgenticTravelState) -> AgenticTravelState:
        try:
            assessment = primary_grader.grade(state["request"], state.get("evidence", []))
        except Exception as exc:
            assessment = fallback_grader.grade(state["request"], state.get("evidence", []))
            degraded, errors = record_dependency_error(state, "evidence_grader", exc)
            return {
                "evidence_assessment": assessment,
                "degraded_components": degraded,
                "dependency_errors": errors,
                "trajectory": event(
                    state,
                    node="grade_evidence",
                    outcome="fallback",
                    reason_codes=assessment.reason_codes,
                    error_type=type(exc).__name__,
                ),
                "status": "grading",
            }
        return {
            "evidence_assessment": assessment,
            "trajectory": event(
                state,
                node="grade_evidence",
                outcome="sufficient" if assessment.sufficient else "insufficient",
                reason_codes=assessment.reason_codes,
            ),
            "status": "grading",
        }

    def route_after_grading(state: AgenticTravelState) -> str:
        if state["evidence_assessment"].sufficient:
            return "generate"
        if state["retrieval_attempts"] < max_retrieval_attempts:
            return "rewrite"
        return "fallback"

    def rewrite_query(state: AgenticTravelState) -> AgenticTravelState:
        attempt = state.get("rewrite_attempts", 0) + 1
        try:
            queries = primary_rewriter.rewrite(
                state["request"],
                state["retrieval_queries"],
                state["evidence_assessment"],
                attempt=attempt,
            )
            if not queries:
                raise ValueError("Query rewriter returned no queries")
        except Exception as exc:
            queries = fallback_rewriter.rewrite(
                state["request"],
                state["retrieval_queries"],
                state["evidence_assessment"],
                attempt=attempt,
            )
            degraded, errors = record_dependency_error(state, "query_rewriter", exc)
            return {
                "retrieval_queries": queries,
                "rewrite_attempts": attempt,
                "degraded_components": degraded,
                "dependency_errors": errors,
                "trajectory": event(
                    state,
                    node="rewrite_query",
                    outcome="fallback",
                    reason_codes=state["evidence_assessment"].missing_aspects,
                    error_type=type(exc).__name__,
                ),
                "status": "rewriting",
            }
        return {
            "retrieval_queries": queries,
            "rewrite_attempts": attempt,
            "trajectory": event(
                state,
                node="rewrite_query",
                outcome="rewritten",
                reason_codes=state["evidence_assessment"].missing_aspects,
            ),
            "status": "rewriting",
        }

    def generate(state: AgenticTravelState) -> AgenticTravelState:
        itinerary = planner.generate(state["request"], state["evidence"])
        return {
            "itinerary": itinerary,
            "trajectory": event(state, node="generate", outcome="generated"),
            "status": "generated",
        }

    def validate(state: AgenticTravelState) -> AgenticTravelState:
        itinerary = state.get("itinerary")
        if itinerary is None:
            return {
                "status": "failed",
                "failure_reason": "Planner returned no itinerary.",
                "trajectory": event(state, node="validate", outcome="missing_itinerary"),
            }
        violations = validate_itinerary(itinerary, state["request"].constraints)
        status = "completed" if not violations else "failed"
        return {
            "violations": violations,
            "status": status,
            "failure_reason": None if not violations else "Itinerary violates constraints.",
            "trajectory": event(state, node="validate", outcome=status),
        }

    def fallback(state: AgenticTravelState) -> AgenticTravelState:
        missing = state["evidence_assessment"].missing_aspects
        suffix = f" Missing aspects: {', '.join(missing)}." if missing else ""
        return {
            "status": "failed",
            "failure_reason": f"Insufficient evidence after bounded retrieval retries.{suffix}",
            "trajectory": event(
                state,
                node="fallback",
                outcome="insufficient_evidence",
                reason_codes=missing,
            ),
        }

    graph = StateGraph(AgenticTravelState)
    nodes: dict[str, Callable] = {
        "initialize": initialize,
        "route_query": route_query,
        "retrieve": retrieve,
        "grade_evidence": grade_evidence,
        "rewrite_query": rewrite_query,
        "generate": generate,
        "validate": validate,
        "fallback": fallback,
    }
    for name, node in nodes.items():
        graph.add_node(name, node)

    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "route_query")
    graph.add_edge("route_query", "retrieve")
    graph.add_edge("retrieve", "grade_evidence")
    graph.add_conditional_edges(
        "grade_evidence",
        route_after_grading,
        {"generate": "generate", "rewrite": "rewrite_query", "fallback": "fallback"},
    )
    graph.add_edge("rewrite_query", "retrieve")
    graph.add_edge("generate", "validate")
    graph.add_edge("validate", END)
    graph.add_edge("fallback", END)
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_after=interrupt_after,
    )
