from __future__ import annotations

from typing import Any

from travelmind.agentic.builder import build_agentic_travel_graph
from travelmind.agentic.models import EvidenceAssessment
from travelmind.planner.demo import DemoPlanner
from travelmind.schemas import Evidence, TravelRequest


def _evidence(identity: str, content: str) -> Evidence:
    return Evidence(
        id=identity,
        content=content,
        source_url="https://example.com/official",
        source_type="official",
        score=1.0,
        metadata={"place_id": "place-1", "name": "Place One", "cost": 20},
    )


class RewriteAwareRetriever:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, queries: list[str], *, limit: int) -> list[Evidence]:
        del queries, limit
        self.calls += 1
        if self.calls == 1:
            return [_evidence("description", "故宫是历史文化景点")]
        return [_evidence("ticket", "故宫官方门票票价为六十元")]


class EmptyRetriever:
    def search(self, queries: list[str], *, limit: int) -> list[Evidence]:
        del queries, limit
        return []


class FlakyRetriever:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, queries: list[str], *, limit: int) -> list[Evidence]:
        del queries, limit
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("downstream request details")
        return [_evidence("ticket", "故宫官方门票票价为六十元")]


class ExplodingRouter:
    def route(self, request: TravelRequest) -> Any:
        del request
        raise RuntimeError("secret=must-not-enter-state")


class ExplodingGrader:
    def grade(self, request: TravelRequest, evidence: list[Evidence]) -> EvidenceAssessment:
        del request, evidence
        raise RuntimeError("grader unavailable")


class ExplodingRewriter:
    def rewrite(self, *args: Any, **kwargs: Any) -> list[str]:
        del args, kwargs
        raise RuntimeError("rewrite prompt and provider details")


def test_agentic_graph_rewrites_missing_aspect_and_recovers() -> None:
    retriever = RewriteAwareRetriever()
    graph = build_agentic_travel_graph(retriever=retriever, planner=DemoPlanner())

    result = graph.invoke({"request": TravelRequest(query="故宫门票")})

    assert result["status"] == "completed"
    assert result["retrieval_attempts"] == 2
    assert result["rewrite_attempts"] == 1
    assert "官方门票" in result["retrieval_queries"][1]
    assert result["evidence_assessment"].sufficient is True
    assert [item.node for item in result["trajectory"]].count("rewrite_query") == 1
    assert [item.attempt for item in result["trajectory"] if item.node == "retrieve"] == [1, 2]


def test_agentic_graph_stops_after_bounded_insufficient_evidence() -> None:
    graph = build_agentic_travel_graph(
        retriever=EmptyRetriever(),
        planner=DemoPlanner(),
        max_retrieval_attempts=2,
    )

    result = graph.invoke({"request": TravelRequest(query="故宫门票")})

    assert result["status"] == "failed"
    assert result["retrieval_attempts"] == 2
    assert result["evidence_assessment"].missing_aspects == ["admission"]
    assert "Missing aspects: admission" in result["failure_reason"]


def test_agentic_graph_rejects_invalid_retrieval_limit() -> None:
    try:
        build_agentic_travel_graph(
            retriever=EmptyRetriever(), planner=DemoPlanner(), retrieval_limit=0
        )
    except ValueError as exc:
        assert str(exc) == "retrieval_limit must be positive"
    else:
        raise AssertionError("Expected invalid retrieval_limit to fail")


def test_agentic_router_failure_uses_deterministic_fallback_without_error_text() -> None:
    graph = build_agentic_travel_graph(
        retriever=RewriteAwareRetriever(),
        planner=DemoPlanner(),
        router=ExplodingRouter(),
    )

    result = graph.invoke({"request": TravelRequest(query="故宫门票")})

    assert result["routing_decision"].retrieval_strategy == "hybrid"
    assert "query_router" in result["degraded_components"]
    assert result["dependency_errors"] == [
        {"component": "query_router", "error_type": "RuntimeError"}
    ]
    assert "secret" not in str(result)


def test_agentic_grader_failure_uses_deterministic_fallback() -> None:
    graph = build_agentic_travel_graph(
        retriever=RewriteAwareRetriever(),
        planner=DemoPlanner(),
        grader=ExplodingGrader(),
    )

    result = graph.invoke({"request": TravelRequest(query="故宫门票")})

    assert result["status"] == "completed"
    assert "evidence_grader" in result["degraded_components"]
    assert all("grader unavailable" not in str(item) for item in result["dependency_errors"])


def test_agentic_retrieval_timeout_rewrites_and_recovers() -> None:
    graph = build_agentic_travel_graph(
        retriever=FlakyRetriever(),
        planner=DemoPlanner(),
    )

    result = graph.invoke({"request": TravelRequest(query="故宫门票")})

    assert result["status"] == "completed"
    assert result["retrieval_attempts"] == 2
    assert "retriever" in result["degraded_components"]
    assert result["dependency_errors"][0]["error_type"] == "TimeoutError"
    assert "downstream request details" not in str(result)


def test_agentic_rewriter_failure_uses_missing_aspect_fallback() -> None:
    graph = build_agentic_travel_graph(
        retriever=RewriteAwareRetriever(),
        planner=DemoPlanner(),
        rewriter=ExplodingRewriter(),
    )

    result = graph.invoke({"request": TravelRequest(query="故宫门票")})

    assert result["status"] == "completed"
    assert "query_rewriter" in result["degraded_components"]
    assert "官方门票" in result["retrieval_queries"][1]
    assert "rewrite prompt" not in str(result)
