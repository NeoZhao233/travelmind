from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from travelmind.agentic.llm_provider import StructuredLLMProvider
from travelmind.domain.models import FactRecord, PlaceRecord
from travelmind.ingestion.dataset import load_jsonl
from travelmind.pipeline import EndToEndPlanningInput, EndToEndPlanningPipeline
from travelmind.planner.candidates import PlaceCandidate, PlanningDayWindow
from travelmind.planner.llm_candidates import (
    DeepSeekRankedPlanningStrategy,
    DeterministicPlanningStrategy,
)
from travelmind.retrieval.base import InMemoryRetriever, Retriever
from travelmind.retrieval.bm25 import BM25Retriever
from travelmind.schemas import (
    OperatingWindow,
    PlaceAvailability,
    TravelConstraints,
    TravelRequest,
    TravelTimeEstimate,
)

_START = datetime(2026, 10, 13, tzinfo=UTC)
_COSTS = {
    "palace-museum": 60.0,
    "summer-palace": 30.0,
    "temple-of-heaven": 34.0,
    "national-museum-china": 0.0,
    "shichahai-park": 0.0,
}
_DURATIONS = {
    "palace-museum": 180,
    "summer-palace": 180,
    "temple-of-heaven": 150,
    "national-museum-china": 120,
    "shichahai-park": 90,
}
_TRAVEL_FROM_HOTEL = {
    "palace-museum": 25,
    "summer-palace": 55,
    "temple-of-heaven": 35,
    "national-museum-china": 25,
    "shichahai-park": 30,
}


class E2EPlanningCase(BaseModel):
    case_id: str
    query: str
    constraints: TravelConstraints
    expected_place_ids: list[str] = Field(min_length=1)
    minimum_expected_hits: int = Field(ge=1)


class E2EPlanningDataset(BaseModel):
    schema_version: int
    selection_gate: dict[str, Any]
    cases: list[E2EPlanningCase] = Field(min_length=1)


def build_selected_hybrid_retriever(root: Path) -> Retriever:
    """Build the Stage 2 selected Hybrid RRF stack from local model artifacts."""

    from travelmind.retrieval.dense import QdrantDenseRetriever
    from travelmind.retrieval.embeddings import BGE_SMALL_ZH_V15, FastEmbedProvider
    from travelmind.retrieval.hybrid import HybridRetriever

    sparse = BM25Retriever.from_project(root)
    embedder = FastEmbedProvider(
        model_name=BGE_SMALL_ZH_V15,
        cache_dir=root / ".cache/fastembed",
        local_files_only=True,
    )
    dense = QdrantDenseRetriever.from_project(root, embedder=embedder)
    return HybridRetriever(
        sparse=sparse,
        dense=dense,
        rrf_k=60,
        candidate_limit=10,
        channel_timeout_seconds=5,
    )


def _catalog(root: Path) -> list[PlaceCandidate]:
    places = load_jsonl(root / "data/seed/places.jsonl", PlaceRecord)
    return [
        PlaceCandidate(
            place_id=place.place_id,
            name=place.name,
            duration_minutes=_DURATIONS[place.place_id],
            estimated_cost=_COSTS[place.place_id],
            interest_tags=place.categories,
            booking_status=("not_required" if place.place_id == "shichahai-park" else "confirmed"),
        )
        for place in places
    ]


def _operational_context(
    catalog: list[PlaceCandidate], days: int
) -> tuple[list[PlaceAvailability], list[TravelTimeEstimate]]:
    availability: list[PlaceAvailability] = []
    travel: list[TravelTimeEstimate] = []
    place_ids = [item.place_id for item in catalog]
    for offset in range(days):
        midnight = _START + timedelta(days=offset)
        service_date = midnight.date()
        for candidate in catalog:
            availability.append(
                PlaceAvailability(
                    place_id=candidate.place_id,
                    service_date=service_date,
                    status="open",
                    windows=[
                        OperatingWindow(
                            opens_at=midnight + timedelta(hours=9),
                            closes_at=midnight + timedelta(hours=18),
                        )
                    ],
                    booking_required=(candidate.booking_status == "confirmed"),
                    evidence_ids=[f"fixture-hours-{candidate.place_id}-{service_date}"],
                    valid_until=midnight + timedelta(hours=23, minutes=59),
                )
            )
        for place_id in place_ids:
            hotel_minutes = _TRAVEL_FROM_HOTEL[place_id]
            for origin, destination, minutes in [
                ("hotel", place_id, hotel_minutes),
                (place_id, "hotel", hotel_minutes),
            ]:
                travel.append(
                    TravelTimeEstimate(
                        origin_place_id=origin,
                        destination_place_id=destination,
                        service_date=service_date,
                        status="known",
                        duration_minutes=minutes,
                        evidence_ids=[f"fixture-route-{origin}-{destination}-{service_date}"],
                        valid_until=midnight + timedelta(hours=23, minutes=59),
                    )
                )
        for origin in place_ids:
            for destination in place_ids:
                if origin == destination:
                    continue
                minutes = 20 + abs(_TRAVEL_FROM_HOTEL[origin] - _TRAVEL_FROM_HOTEL[destination])
                travel.append(
                    TravelTimeEstimate(
                        origin_place_id=origin,
                        destination_place_id=destination,
                        service_date=service_date,
                        status="known",
                        duration_minutes=minutes,
                        evidence_ids=[f"fixture-route-{origin}-{destination}-{service_date}"],
                        valid_until=midnight + timedelta(hours=23, minutes=59),
                    )
                )
    return availability, travel


def _runtime_input(
    root: Path,
    case: E2EPlanningCase,
    catalog: list[PlaceCandidate],
) -> EndToEndPlanningInput:
    days = case.constraints.days or 1
    availability, travel = _operational_context(catalog, days)
    return EndToEndPlanningInput(
        request=TravelRequest(query=case.query, constraints=case.constraints),
        day_windows=[
            PlanningDayWindow(
                day=offset + 1,
                available_from=_START + timedelta(days=offset, hours=8, minutes=30),
                available_until=_START + timedelta(days=offset, hours=18, minutes=30),
                origin_place_id="hotel",
            )
            for offset in range(days)
        ],
        candidate_catalog=catalog,
        availability=availability,
        travel_times=travel,
        minimum_transfer_buffer_minutes=15,
    )


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    calls = [row["planner_call"] for row in rows if row["planner_call"] is not None]
    successful_calls = [call for call in calls if call["success"]]
    return {
        "task_success_rate": sum(row["task_success"] for row in rows) / len(rows),
        "valid_plan_rate": sum(row["valid_plan"] for row in rows) / len(rows),
        "constraint_satisfaction_rate": sum(row["constraint_satisfied"] for row in rows)
        / len(rows),
        "required_place_coverage": sum(row["required_coverage"] for row in rows) / len(rows),
        "expected_place_hit_rate": sum(row["expected_hit_rate"] for row in rows) / len(rows),
        "expected_place_precision": sum(row["expected_place_precision"] for row in rows)
        / len(rows),
        "mean_selected_place_count": sum(len(row["selected_place_ids"]) for row in rows)
        / len(rows),
        "repair_activation_rate": sum(row["repair_attempts"] > 0 for row in rows) / len(rows),
        "fallback_rate": (
            sum(call["fallback_used"] for call in calls) / len(calls) if calls else 0.0
        ),
        "total_provider_tokens": sum(call["total_tokens"] for call in calls),
        "mean_provider_latency_ms": (
            sum(call["latency_ms"] for call in successful_calls) / len(successful_calls)
            if successful_calls
            else None
        ),
        "mean_estimated_context_tokens": sum(row["estimated_context_tokens"] for row in rows)
        / len(rows),
    }


def run_e2e_planning_experiment(
    root: Path,
    *,
    provider: StructuredLLMProvider | None = None,
    retriever: Retriever | None = None,
    retriever_name: str = "bm25",
) -> dict[str, Any]:
    root = root.resolve()
    dataset_path = root / "evals/datasets/e2e_planning_seed.json"
    raw = dataset_path.read_bytes()
    dataset = E2EPlanningDataset.model_validate_json(raw)
    base_retriever = retriever or BM25Retriever.from_project(root)
    catalog = _catalog(root)
    aspects: dict[str, set[str]] = {}
    for fact in load_jsonl(root / "data/seed/facts.jsonl", FactRecord):
        aspects.setdefault(fact.document_id, set()).add(fact.fact_type.value)
    variants = {"deterministic": DeterministicPlanningStrategy()}
    if provider is not None:
        variants["deepseek_ranked"] = DeepSeekRankedPlanningStrategy(provider)
    rows: list[dict[str, Any]] = []
    for case in dataset.cases:
        retrieved = base_retriever.search([case.query], limit=10)
        for variant, strategy in variants.items():
            pipeline = EndToEndPlanningPipeline(
                retriever=InMemoryRetriever(retrieved),
                planning_strategy=strategy,
                aspects_by_document=aspects,
                retrieval_limit=10,
                max_repair_attempts=2,
            )
            result = pipeline.run(_runtime_input(root, case, catalog))
            selected = (
                [activity.place_id for day in result.itinerary.days for activity in day.activities]
                if result.itinerary is not None
                else []
            )
            required = set(case.constraints.required_places)
            required_coverage = len(required & set(selected)) / len(required) if required else 1.0
            expected_hits = len(set(case.expected_place_ids) & set(selected))
            expected_hit_rate = expected_hits / len(case.expected_place_ids)
            expected_place_precision = expected_hits / len(selected) if selected else 0.0
            valid = result.status == "completed" and not result.violations
            task_success = (
                valid and required_coverage == 1 and expected_hits >= case.minimum_expected_hits
            )
            rows.append(
                {
                    "case_id": case.case_id,
                    "variant": variant,
                    "selected_place_ids": selected,
                    "task_success": task_success,
                    "valid_plan": valid,
                    "constraint_satisfied": not result.violations,
                    "required_coverage": required_coverage,
                    "expected_hit_rate": expected_hit_rate,
                    "expected_place_precision": expected_place_precision,
                    "repair_attempts": result.repair_attempts,
                    "retrieved_evidence_count": result.retrieved_evidence_count,
                    "packed_evidence_count": result.packed_evidence_count,
                    "candidate_count": result.candidate_count,
                    "estimated_context_tokens": result.estimated_context_tokens,
                    "planner_call": (
                        result.planner_call.model_dump(mode="json")
                        if result.planner_call is not None
                        else None
                    ),
                    "failure_reason": result.failure_reason,
                }
            )
    metrics = {
        variant: _metrics([row for row in rows if row["variant"] == variant])
        for variant in variants
    }
    selection: dict[str, Any]
    if "deepseek_ranked" not in metrics:
        selection = {
            "status": "candidate_not_run",
            "selected_planner": "deterministic",
            "gate_passed": False,
        }
    else:
        baseline = metrics["deterministic"]
        candidate = metrics["deepseek_ranked"]
        lift = candidate["expected_place_hit_rate"] - baseline["expected_place_hit_rate"]
        gate = (
            candidate["valid_plan_rate"] >= baseline["valid_plan_rate"]
            and candidate["constraint_satisfaction_rate"]
            >= baseline["constraint_satisfaction_rate"]
            and candidate["expected_place_hit_rate"] >= baseline["expected_place_hit_rate"]
            and lift >= dataset.selection_gate["minimum_expected_place_hit_rate_lift"]
            and candidate["fallback_rate"]
            <= dataset.selection_gate["maximum_candidate_fallback_rate"]
        )
        selection = {
            "status": "selected" if gate else "baseline_retained",
            "selected_planner": "deepseek_ranked" if gate else "deterministic",
            "gate_passed": gate,
            "expected_place_hit_rate_lift": lift,
        }
    return {
        "experiment": "stage5d-end-to-end-planning-ablation",
        "dataset": str(dataset_path.relative_to(root)),
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "retriever": retriever_name,
        "context_pipeline": "refined-coverage-768",
        "planner_variants": list(variants),
        "selection_gate": dataset.selection_gate,
        "metrics": metrics,
        "selection": selection,
        "cases": rows,
        "limitations": [
            "Five project-authored non-blind cases are a pilot, not a benchmark.",
            "Opening hours, booking state, prices, and travel times are controlled fixtures.",
            "The LLM ranks soft preferences; deterministic code owns scheduling and validation.",
            "Expected-place matching does not measure narrative usefulness or route realism.",
        ],
    }
