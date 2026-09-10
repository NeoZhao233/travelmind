from travelmind.graph.builder import build_travel_graph
from travelmind.planner.demo import DemoPlanner
from travelmind.retrieval.base import InMemoryRetriever
from travelmind.schemas import Evidence, TravelRequest


def test_graph_completes_with_evidence() -> None:
    retriever = InMemoryRetriever(
        [
            Evidence(
                id="doc-1",
                content="An official place description.",
                source_url="https://example.com/place",
                source_type="official",
                score=0.9,
                metadata={"place_id": "place-1", "name": "Place One", "cost": 20},
            )
        ]
    )
    graph = build_travel_graph(retriever=retriever, planner=DemoPlanner())

    result = graph.invoke({"request": TravelRequest(query="Plan a trip")})

    assert result["status"] == "completed"
    assert result["retrieval_attempts"] == 1
    assert result["itinerary"] is not None


def test_graph_stops_after_bounded_retrieval_retries() -> None:
    graph = build_travel_graph(
        retriever=InMemoryRetriever([]),
        planner=DemoPlanner(),
        max_retrieval_attempts=2,
    )

    result = graph.invoke({"request": TravelRequest(query="Unknown destination")})

    assert result["status"] == "failed"
    assert result["retrieval_attempts"] == 2
    assert "Insufficient evidence" in result["failure_reason"]
