from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from travelmind.graph.state import TravelAgentState
from travelmind.planner.base import Planner
from travelmind.planner.constraints import validate_itinerary
from travelmind.retrieval.base import Retriever


def build_travel_graph(
    *,
    retriever: Retriever,
    planner: Planner,
    max_retrieval_attempts: int = 2,
    evidence_threshold: int = 1,
):
    """Build a bounded retrieval-and-planning graph with injectable dependencies."""

    if max_retrieval_attempts < 1:
        raise ValueError("max_retrieval_attempts must be positive")
    if evidence_threshold < 1:
        raise ValueError("evidence_threshold must be positive")

    def initialize(state: TravelAgentState) -> TravelAgentState:
        request = state["request"]
        return {
            "retrieval_queries": [request.query],
            "evidence": [],
            "violations": [],
            "retrieval_attempts": 0,
            "status": "initialized",
            "failure_reason": None,
        }

    def retrieve(state: TravelAgentState) -> TravelAgentState:
        evidence = retriever.search(state["retrieval_queries"], limit=10)
        return {
            "evidence": evidence,
            "retrieval_attempts": state["retrieval_attempts"] + 1,
            "status": "retrieving",
        }

    def grade_retrieval(state: TravelAgentState) -> TravelAgentState:
        if len(state["evidence"]) >= evidence_threshold:
            return {"status": "retrieving"}
        return {"status": "insufficient_evidence"}

    def route_after_grading(state: TravelAgentState) -> str:
        if len(state["evidence"]) >= evidence_threshold:
            return "generate"
        if state["retrieval_attempts"] < max_retrieval_attempts:
            return "rewrite"
        return "fallback"

    def rewrite_query(state: TravelAgentState) -> TravelAgentState:
        original = state["request"].query
        retry_number = state["retrieval_attempts"] + 1
        return {
            "retrieval_queries": [
                original,
                f"{original} 官方信息 营业时间 门票 交通 第{retry_number}次检索",
            ]
        }

    def generate(state: TravelAgentState) -> TravelAgentState:
        itinerary = planner.generate(state["request"], state["evidence"])
        return {"itinerary": itinerary, "status": "generated"}

    def validate(state: TravelAgentState) -> TravelAgentState:
        itinerary = state.get("itinerary")
        if itinerary is None:
            return {"status": "failed", "failure_reason": "Planner returned no itinerary."}
        violations = validate_itinerary(itinerary, state["request"].constraints)
        return {
            "violations": violations,
            "status": "completed" if not violations else "failed",
            "failure_reason": None if not violations else "Itinerary violates constraints.",
        }

    def fallback(_: TravelAgentState) -> TravelAgentState:
        return {
            "status": "failed",
            "failure_reason": "Insufficient evidence after bounded retrieval retries.",
        }

    graph = StateGraph(TravelAgentState)
    nodes: dict[str, Callable] = {
        "initialize": initialize,
        "retrieve": retrieve,
        "grade_retrieval": grade_retrieval,
        "rewrite_query": rewrite_query,
        "generate": generate,
        "validate": validate,
        "fallback": fallback,
    }
    for name, node in nodes.items():
        graph.add_node(name, node)

    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "retrieve")
    graph.add_edge("retrieve", "grade_retrieval")
    graph.add_conditional_edges(
        "grade_retrieval",
        route_after_grading,
        {"generate": "generate", "rewrite": "rewrite_query", "fallback": "fallback"},
    )
    graph.add_edge("rewrite_query", "retrieve")
    graph.add_edge("generate", "validate")
    graph.add_edge("validate", END)
    graph.add_edge("fallback", END)
    return graph.compile()
