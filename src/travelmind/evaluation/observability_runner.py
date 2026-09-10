from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from travelmind.evaluation.e2e_planning_runner import _catalog, _operational_context
from travelmind.observability import InMemoryTelemetrySink
from travelmind.pipeline import EndToEndPlanningInput, EndToEndPlanningPipeline
from travelmind.planner.candidates import PlanningDayWindow
from travelmind.planner.llm_candidates import DeterministicPlanningStrategy
from travelmind.retrieval.bm25 import BM25Retriever
from travelmind.schemas import TravelConstraints, TravelRequest

_CANARY = "sensitive-canary-do-not-log"
_TRACE_IDS = {
    "healthy": "00000000000000000000000000000001",
    "telemetry_outage": "00000000000000000000000000000002",
    "retrieval_fallback": "00000000000000000000000000000003",
}


class _BrokenSink:
    def emit(self, event) -> None:
        del event
        raise TimeoutError(f"telemetry outage {_CANARY}")


class _BrokenRetriever:
    def search(self, queries: list[str], *, limit: int):
        del queries, limit
        raise TimeoutError(f"retrieval outage {_CANARY}")


def _input(root: Path) -> EndToEndPlanningInput:
    catalog = _catalog(root)
    availability, travel = _operational_context(catalog, 1)
    return EndToEndPlanningInput(
        request=TravelRequest(
            query=f"喜欢皇家园林和湖景 {_CANARY}",
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


def run_observability_drill(root: Path) -> dict:
    root = root.resolve()
    bm25 = BM25Retriever.from_project(root)
    scenarios = [
        ("healthy", bm25, None, InMemoryTelemetrySink()),
        ("telemetry_outage", bm25, None, _BrokenSink()),
        ("retrieval_fallback", _BrokenRetriever(), bm25, InMemoryTelemetrySink()),
    ]
    rows = []
    for name, retriever, fallback, sink in scenarios:
        result = EndToEndPlanningPipeline(
            retriever=retriever,
            fallback_retriever=fallback,
            planning_strategy=DeterministicPlanningStrategy(),
            telemetry_sink=sink,
            trace_id_factory=lambda identity=_TRACE_IDS[name]: identity,
        ).run(_input(root))
        events = sink.events if isinstance(sink, InMemoryTelemetrySink) else []
        serialized_events = "".join(event.model_dump_json() for event in events)
        rows.append(
            {
                "scenario": name,
                "business_completed": result.status == "completed",
                "trace_id": result.trace_id,
                "telemetry_degraded": result.telemetry_degraded,
                "degraded_components": result.degraded_components,
                "event_count": len(events),
                "sequence_contiguous": [event.sequence for event in events]
                == list(range(1, len(events) + 1)),
                "trace_correlated": all(event.trace_id == result.trace_id for event in events),
                "canary_leaked": _CANARY in serialized_events
                or _CANARY in result.model_dump_json(),
                "safe_error_types": sorted(
                    {event.error_type for event in events if event.error_type is not None}
                ),
            }
        )
    return {
        "experiment": "stage7a-observability-and-redaction-drill",
        "configuration_sha256": hashlib.sha256(
            b"telemetry-v1|healthy|telemetry_outage|retrieval_fallback"
        ).hexdigest(),
        "metrics": {
            "business_completion_rate": sum(row["business_completed"] for row in rows) / len(rows),
            "canary_leak_rate": sum(row["canary_leaked"] for row in rows) / len(rows),
            "trace_integrity_rate_when_sink_available": sum(
                row["sequence_contiguous"] and row["trace_correlated"]
                for row in rows
                if row["event_count"] > 0
            )
            / sum(row["event_count"] > 0 for row in rows),
            "telemetry_outage_survival_rate": float(
                next(
                    row["business_completed"] and row["telemetry_degraded"]
                    for row in rows
                    if row["scenario"] == "telemetry_outage"
                )
            ),
            "retrieval_fallback_visibility_rate": float(
                next(
                    row["business_completed"]
                    and row["degraded_components"] == ["retriever"]
                    and "TimeoutError" in row["safe_error_types"]
                    for row in rows
                    if row["scenario"] == "retrieval_fallback"
                )
            ),
        },
        "cases": rows,
        "limitations": [
            "The sink is in-memory; remote exporter delivery is not measured.",
            "The drill uses injected exceptions rather than a real collector outage.",
            "Metrics validate trace contracts, not production throughput or cardinality cost.",
        ],
    }
