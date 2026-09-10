from datetime import UTC, datetime
from pathlib import Path

from travelmind.evaluation.e2e_planning_runner import (
    _catalog,
    _operational_context,
)
from travelmind.observability import InMemoryTelemetrySink, RunTelemetry
from travelmind.pipeline import EndToEndPlanningInput, EndToEndPlanningPipeline
from travelmind.planner.candidates import PlanningDayWindow
from travelmind.planner.llm_candidates import DeterministicPlanningStrategy
from travelmind.retrieval.bm25 import BM25Retriever
from travelmind.schemas import TravelConstraints, TravelRequest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRACE_ID = "0123456789abcdef0123456789abcdef"


def _runtime_input(query: str) -> EndToEndPlanningInput:
    catalog = _catalog(PROJECT_ROOT)
    availability, travel = _operational_context(catalog, 1)
    return EndToEndPlanningInput(
        request=TravelRequest(
            query=query,
            constraints=TravelConstraints(
                destination="北京",
                days=1,
                required_places=["summer-palace"],
            ),
        ),
        day_windows=[
            PlanningDayWindow(
                day=1,
                available_from=datetime(2026, 10, 13, 8, 30, tzinfo=UTC),
                available_until=datetime(2026, 10, 13, 18, 30, tzinfo=UTC),
                origin_place_id="hotel",
            )
        ],
        candidate_catalog=catalog,
        availability=availability,
        travel_times=travel,
    )


def test_allowlist_drops_unknown_or_sensitive_attributes() -> None:
    sink = InMemoryTelemetrySink()
    telemetry = RunTelemetry(TRACE_ID, sink)

    telemetry.emit(
        component="test",
        operation="sanitize",
        status="succeeded",
        attributes={"evidence_count": 2, "user_query": "API_KEY=secret"},
    )

    assert sink.events[0].attributes == {
        "evidence_count": 2,
        "dropped_attribute_count": 1,
    }
    assert "secret" not in sink.events[0].model_dump_json()


def test_e2e_pipeline_emits_correlated_redacted_stage_events() -> None:
    sink = InMemoryTelemetrySink()
    secret = "API_KEY=do-not-log"
    pipeline = EndToEndPlanningPipeline(
        retriever=BM25Retriever.from_project(PROJECT_ROOT),
        planning_strategy=DeterministicPlanningStrategy(),
        telemetry_sink=sink,
        trace_id_factory=lambda: TRACE_ID,
    )

    result = pipeline.run(_runtime_input(f"皇家园林和湖景 {secret}"))

    assert result.status == "completed"
    assert result.trace_id == TRACE_ID
    assert result.telemetry_degraded is False
    assert [event.sequence for event in sink.events] == list(range(1, len(sink.events) + 1))
    assert {event.component for event in sink.events} >= {
        "planning_pipeline",
        "retriever",
        "context_builder",
        "candidate_builder",
        "planner",
    }
    assert all(event.trace_id == TRACE_ID for event in sink.events)
    assert secret not in "".join(event.model_dump_json() for event in sink.events)


class BrokenSink:
    def emit(self, event) -> None:
        del event
        raise TimeoutError("telemetry backend leaked-secret")


def test_telemetry_outage_does_not_break_planning() -> None:
    pipeline = EndToEndPlanningPipeline(
        retriever=BM25Retriever.from_project(PROJECT_ROOT),
        planning_strategy=DeterministicPlanningStrategy(),
        telemetry_sink=BrokenSink(),
        trace_id_factory=lambda: TRACE_ID,
    )

    result = pipeline.run(_runtime_input("喜欢皇家园林和湖景"))

    assert result.status == "completed"
    assert result.telemetry_degraded is True
    assert "leaked-secret" not in result.model_dump_json()
