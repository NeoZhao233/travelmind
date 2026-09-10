from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from travelmind.evaluation.e2e_planning_runner import _catalog, _operational_context
from travelmind.observability import InMemoryTelemetrySink
from travelmind.pipeline import EndToEndPlanningInput, EndToEndPlanningPipeline
from travelmind.planner.candidates import PlanningDayWindow
from travelmind.planner.llm_candidates import (
    DeepSeekRankedPlanningStrategy,
    DeterministicPlanningStrategy,
)
from travelmind.retrieval.bm25 import BM25Retriever
from travelmind.schemas import TravelConstraints, TravelRequest

_CANARY = "stage7d-sensitive-canary"
_MAX_RECOVERABLE_LATENCY_MS = 5_000
_MAX_SAFE_FAILURE_LATENCY_MS = 1_000


class _BrokenDependency:
    def search(self, queries: list[str], *, limit: int):
        del queries, limit
        raise TimeoutError(f"retrieval outage {_CANARY}")

    def complete_json(self, **kwargs):
        del kwargs
        raise TimeoutError(f"model outage {_CANARY}")

    def emit(self, event) -> None:
        del event
        raise TimeoutError(f"telemetry outage {_CANARY}")


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


def _run(pipeline: EndToEndPlanningPipeline, runtime_input: EndToEndPlanningInput):
    started = perf_counter()
    result = pipeline.run(runtime_input)
    return result, (perf_counter() - started) * 1_000


def run_slo_outage_drill(root: Path) -> dict:
    """Exercise pre-release objectives; this is not an observed production SLO."""

    project_root = root.resolve()
    runtime_input = _input(project_root)
    bm25 = BM25Retriever.from_project(project_root)
    broken = _BrokenDependency()

    healthy_sink = InMemoryTelemetrySink()
    healthy, healthy_latency = _run(
        EndToEndPlanningPipeline(
            retriever=bm25,
            planning_strategy=DeterministicPlanningStrategy(),
            telemetry_sink=healthy_sink,
            trace_id_factory=lambda: "00000000000000000000000000000011",
        ),
        runtime_input,
    )
    recoverable, recoverable_latency = _run(
        EndToEndPlanningPipeline(
            retriever=broken,
            fallback_retriever=bm25,
            planning_strategy=DeepSeekRankedPlanningStrategy(broken),
            telemetry_sink=broken,
            trace_id_factory=lambda: "00000000000000000000000000000012",
        ),
        runtime_input,
    )
    failed_sink = InMemoryTelemetrySink()
    unrecoverable, unrecoverable_latency = _run(
        EndToEndPlanningPipeline(
            retriever=broken,
            fallback_retriever=broken,
            planning_strategy=DeterministicPlanningStrategy(),
            telemetry_sink=failed_sink,
            trace_id_factory=lambda: "00000000000000000000000000000013",
        ),
        runtime_input,
    )

    serialized = "".join(
        [
            healthy.model_dump_json(),
            recoverable.model_dump_json(),
            unrecoverable.model_dump_json(),
            *(event.model_dump_json() for event in healthy_sink.events),
            *(event.model_dump_json() for event in failed_sink.events),
        ]
    )
    recoverable_visible = (
        recoverable.degraded_components == ["retriever"]
        and recoverable.telemetry_degraded
        and recoverable.planner_call is not None
        and recoverable.planner_call.fallback_used
        and recoverable.planner_call.error_type == "TimeoutError"
    )
    unrecoverable_safe = (
        unrecoverable.status == "failed"
        and unrecoverable.itinerary is None
        and unrecoverable.degraded_components == ["retriever", "fallback_retriever"]
        and unrecoverable.failure_reason == "Both retrieval paths failed."
    )
    checks = {
        "healthy_path_completed": healthy.status == "completed",
        "recoverable_composite_outage_completed": recoverable.status == "completed",
        "all_three_degradations_visible": recoverable_visible,
        "unrecoverable_retrieval_outage_failed_safely": unrecoverable_safe,
        "recoverable_latency_within_objective": (
            recoverable_latency <= _MAX_RECOVERABLE_LATENCY_MS
        ),
        "safe_failure_latency_within_objective": (
            unrecoverable_latency <= _MAX_SAFE_FAILURE_LATENCY_MS
        ),
        "sensitive_canary_not_exposed": _CANARY not in serialized,
    }
    return {
        "experiment": "stage7d-pre-release-slo-and-composite-outage-drill",
        "configuration_sha256": hashlib.sha256(
            b"slo-v1|retrieval+model+telemetry|dual-retrieval-outage"
        ).hexdigest(),
        "objective_type": "synthetic_pre_release_gate",
        "objectives": {
            "recoverable_composite_completion_rate_min": 1.0,
            "unrecoverable_safe_failure_rate_min": 1.0,
            "degradation_visibility_rate_min": 1.0,
            "canary_leak_rate_max": 0.0,
            "recoverable_latency_ms_max": _MAX_RECOVERABLE_LATENCY_MS,
            "safe_failure_latency_ms_max": _MAX_SAFE_FAILURE_LATENCY_MS,
        },
        "checks": checks,
        "metrics": {
            "check_pass_rate": sum(checks.values()) / len(checks),
            "recoverable_composite_completion_rate": float(recoverable.status == "completed"),
            "unrecoverable_safe_failure_rate": float(unrecoverable_safe),
            "degradation_visibility_rate": float(recoverable_visible),
            "canary_leak_rate": float(_CANARY in serialized),
            "recoverable_latency_ms": recoverable_latency,
            "safe_failure_latency_ms": unrecoverable_latency,
        },
        "cases": [
            {
                "scenario": "healthy",
                "status": healthy.status,
                "latency_ms": healthy_latency,
            },
            {
                "scenario": "retrieval_model_telemetry_outage",
                "status": recoverable.status,
                "latency_ms": recoverable_latency,
                "retrieval_fallback": "retriever" in recoverable.degraded_components,
                "model_fallback": bool(
                    recoverable.planner_call and recoverable.planner_call.fallback_used
                ),
                "telemetry_degraded": recoverable.telemetry_degraded,
            },
            {
                "scenario": "primary_and_fallback_retrieval_outage",
                "status": unrecoverable.status,
                "latency_ms": unrecoverable_latency,
                "failure_reason": unrecoverable.failure_reason,
            },
        ],
        "limitations": [
            "These are synthetic pre-release gates, not production traffic SLO measurements.",
            "One local sample per scenario cannot establish a latency percentile distribution.",
            "Injected exceptions do not reproduce network partitions, saturation, "
            "or correlated infrastructure loss.",
        ],
    }
