from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from travelmind.planner.candidates import PlaceCandidate
from travelmind.repair import build_itinerary_repair_graph
from travelmind.schemas import (
    Activity,
    DayPlan,
    Itinerary,
    OperatingWindow,
    PlaceAvailability,
    PlanningValidationContext,
    TravelConstraints,
    TravelTimeEstimate,
)

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


class RepairEvaluationCase(BaseModel):
    case_id: str
    scenario: Literal[
        "valid",
        "cost_mismatch",
        "budget",
        "closed_day",
        "impossible",
        "nonrepairable",
        "repairer_outage",
    ]
    expected_status: Literal["completed", "failed"]
    expected_attempts: int
    expected_modified_days: list[int]


class _ExplodingRepairer:
    def repair(self, request: Any) -> Any:
        del request
        raise TimeoutError("provider payload must not enter state")


def _activity(place_id: str, day: int, cost: float = 10) -> Activity:
    start = _BASE + timedelta(days=day - 1, hours=9)
    return Activity(
        place_id=place_id,
        name=place_id,
        start_at=start,
        end_at=start + timedelta(hours=1),
        estimated_cost=cost,
        evidence_ids=[f"doc-{place_id}"],
        booking_status="not_required",
    )


def _day(day: int, activities: list[Activity], *, bounded: bool = False) -> DayPlan:
    if not bounded:
        return DayPlan(day=day, activities=activities)
    start = _BASE + timedelta(days=day - 1, hours=8)
    return DayPlan(
        day=day,
        activities=activities,
        available_from=start,
        available_until=start + timedelta(hours=10),
        origin_place_id="hotel",
    )


def _availability(place_id: str, service_date: date, status: str) -> PlaceAvailability:
    midnight = datetime.combine(service_date, datetime.min.time(), tzinfo=UTC)
    return PlaceAvailability(
        place_id=place_id,
        service_date=service_date,
        status=status,
        windows=(
            [
                OperatingWindow(
                    opens_at=midnight + timedelta(hours=8),
                    closes_at=midnight + timedelta(hours=18),
                )
            ]
            if status == "open"
            else []
        ),
        evidence_ids=[f"hours-{place_id}"],
    )


def _travel(origin: str, destination: str, service_date: date) -> TravelTimeEstimate:
    return TravelTimeEstimate(
        origin_place_id=origin,
        destination_place_id=destination,
        service_date=service_date,
        status="known",
        duration_minutes=15,
        evidence_ids=[f"route-{origin}-{destination}"],
    )


def _inputs(scenario: str) -> tuple[dict[str, Any], dict[str, Any]]:
    permissive = PlanningValidationContext(fail_closed_on_missing_availability=False)
    if scenario in {"valid", "cost_mismatch", "repairer_outage"}:
        itinerary = Itinerary(
            days=[_day(1, [_activity("safe", 1)])],
            estimated_total_cost=1 if scenario != "valid" else 10,
        )
        return (
            {
                "itinerary": itinerary,
                "constraints": TravelConstraints(days=1),
                "context": permissive,
                "candidates": [],
            },
            {"preserved_day": itinerary.days[0].model_dump(mode="json")},
        )
    if scenario == "budget":
        itinerary = Itinerary(
            days=[
                _day(
                    1,
                    [
                        _activity("required", 1, 60),
                        _activity("optional", 1, 50),
                    ],
                )
            ],
            estimated_total_cost=110,
        )
        return (
            {
                "itinerary": itinerary,
                "constraints": TravelConstraints(days=1, budget=70, required_places=["required"]),
                "context": permissive,
                "candidates": [],
            },
            {},
        )
    if scenario == "closed_day":
        first_date = _BASE.date()
        second_date = (_BASE + timedelta(days=1)).date()
        second_day = _day(2, [_activity("safe", 2)], bounded=True)
        itinerary = Itinerary(
            days=[_day(1, [_activity("closed", 1)], bounded=True), second_day],
            estimated_total_cost=20,
        )
        context = PlanningValidationContext(
            availability=[
                _availability("closed", first_date, "closed"),
                _availability("alternative", first_date, "open"),
                _availability("safe", second_date, "open"),
            ],
            travel_times=[
                _travel("hotel", "closed", first_date),
                _travel("closed", "hotel", first_date),
                _travel("hotel", "alternative", first_date),
                _travel("alternative", "hotel", first_date),
                _travel("hotel", "safe", second_date),
                _travel("safe", "hotel", second_date),
            ],
            minimum_transfer_buffer_minutes=15,
        )
        candidates = [
            PlaceCandidate(
                place_id=place_id,
                name=place_id,
                duration_minutes=60,
                estimated_cost=cost,
                relevance_score=relevance,
                evidence_ids=[f"doc-{place_id}"],
                booking_status="not_required",
            )
            for place_id, cost, relevance in [
                ("closed", 10, 0.5),
                ("alternative", 15, 0.8),
                ("safe", 10, 0.5),
            ]
        ]
        return (
            {
                "itinerary": itinerary,
                "constraints": TravelConstraints(days=2, pace="relaxed"),
                "context": context,
                "candidates": candidates,
            },
            {"preserved_day": second_day.model_dump(mode="json")},
        )
    if scenario == "nonrepairable":
        return (
            {
                "itinerary": Itinerary(
                    days=[DayPlan(day=1), DayPlan(day=1)],
                    estimated_total_cost=0,
                ),
                "constraints": TravelConstraints(days=2),
                "context": permissive,
                "candidates": [],
            },
            {},
        )
    service_date = _BASE.date()
    itinerary = Itinerary(days=[_day(1, [], bounded=True)], estimated_total_cost=0)
    candidate = PlaceCandidate(
        place_id="required",
        name="required",
        duration_minutes=60,
        estimated_cost=0,
        evidence_ids=["doc-required"],
    )
    return (
        {
            "itinerary": itinerary,
            "constraints": TravelConstraints(days=1, required_places=["required"]),
            "context": PlanningValidationContext(
                availability=[_availability("required", service_date, "open")]
            ),
            "candidates": [candidate],
        },
        {},
    )


def run_repair_experiment(project_root: Path) -> dict[str, Any]:
    dataset_path = project_root / "evals/datasets/repair_seed.json"
    raw = dataset_path.read_bytes()
    cases = [RepairEvaluationCase.model_validate(item) for item in json.loads(raw.decode("utf-8"))]
    outputs: list[dict[str, Any]] = []
    exact = 0
    repairable_success = 0
    repairable_cases = 0
    safe_failures = 0
    failure_cases = 0
    preservation_checks = 0
    preserved = 0
    fallback_cases = 0
    fallback_recoveries = 0
    total_attempts = 0

    for case in cases:
        inputs, probes = _inputs(case.scenario)
        repairer = _ExplodingRepairer() if case.scenario == "repairer_outage" else None
        graph = build_itinerary_repair_graph(repairer=repairer, max_repair_attempts=2)
        result = graph.invoke(inputs)
        total_attempts += result["repair_attempts"]
        matched = (
            result["status"] == case.expected_status
            and result["repair_attempts"] == case.expected_attempts
            and result["modified_days"] == case.expected_modified_days
        )
        exact += int(matched)
        if case.expected_status == "completed" and case.scenario != "valid":
            repairable_cases += 1
            repairable_success += int(result["status"] == "completed")
        if case.expected_status == "failed":
            failure_cases += 1
            safe_failures += int(result["status"] == "failed" and bool(result["violations"]))
        if case.scenario == "closed_day":
            preservation_checks += 1
            preserved += int(
                result["itinerary"].days[1].model_dump(mode="json") == probes["preserved_day"]
            )
        if case.scenario == "repairer_outage":
            fallback_cases += 1
            fallback_recoveries += int(
                result["status"] == "completed"
                and "itinerary_repairer" in result["degraded_components"]
            )
        outputs.append(
            {
                "case_id": case.case_id,
                "status": result["status"],
                "repair_attempts": result["repair_attempts"],
                "modified_days": result["modified_days"],
                "final_violation_codes": sorted({item.code for item in result["violations"]}),
                "degraded_components": result["degraded_components"],
                "exact_match": matched,
            }
        )

    return {
        "experiment": "stage5c-bounded-local-repair",
        "dataset": str(dataset_path.relative_to(project_root)),
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "configuration": {"max_repair_attempts": 2},
        "metrics": {
            "case_count": len(cases),
            "expected_outcome_exact_match": exact / len(cases),
            "repairable_case_success_rate": repairable_success / repairable_cases,
            "safe_failure_accuracy": safe_failures / failure_cases,
            "unaffected_day_preservation_rate": preserved / preservation_checks,
            "repairer_outage_recovery_rate": fallback_recoveries / fallback_cases,
            "mean_repair_attempts": total_attempts / len(cases),
        },
        "limitations": [
            "Project-authored deterministic fixtures, not independently reviewed traffic.",
            "Local repair replans an affected day; activity-level rescheduling is limited.",
            "No real LLM repair candidate is evaluated in Stage 5C.",
        ],
        "cases": outputs,
    }
