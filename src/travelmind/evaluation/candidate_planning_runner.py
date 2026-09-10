from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from travelmind.planner.candidates import (
    CandidatePlanningProblem,
    ExplainableGreedyPlanner,
    PlaceCandidate,
    PlanningDayWindow,
)
from travelmind.schemas import (
    OperatingWindow,
    PlaceAvailability,
    TravelConstraints,
    TravelTimeEstimate,
)


class CandidateFixture(BaseModel):
    place_id: str
    duration_minutes: int
    cost: float
    relevance: float
    interest_tags: list[str] = Field(default_factory=list)
    booking_required: bool = False
    booking_status: str = "unknown"
    status: str = "open"


class CandidatePlanningCase(BaseModel):
    case_id: str
    constraints: TravelConstraints
    candidates: list[CandidateFixture]
    edges: list[tuple[str, str, int]]
    expected_selected: list[str]
    expected_unscheduled_required: list[str]
    expected_skips: dict[str, str]


def _build_problem(case: CandidatePlanningCase) -> CandidatePlanningProblem:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candidates = [
        PlaceCandidate(
            place_id=item.place_id,
            name=item.place_id,
            duration_minutes=item.duration_minutes,
            estimated_cost=item.cost,
            relevance_score=item.relevance,
            interest_tags=item.interest_tags,
            evidence_ids=[f"doc-{item.place_id}"],
            booking_status=item.booking_status,
        )
        for item in case.candidates
    ]
    availability = [
        PlaceAvailability(
            place_id=item.place_id,
            service_date=base.date(),
            status=item.status,
            windows=(
                [
                    OperatingWindow(
                        opens_at=base + timedelta(hours=8),
                        closes_at=base + timedelta(hours=18),
                    )
                ]
                if item.status == "open"
                else []
            ),
            booking_required=item.booking_required,
            evidence_ids=[f"hours-{item.place_id}"],
        )
        for item in case.candidates
        if item.place_id not in case.constraints.excluded_places
    ]
    travel_times = [
        TravelTimeEstimate(
            origin_place_id=origin,
            destination_place_id=destination,
            service_date=base.date(),
            status="known",
            duration_minutes=minutes,
            evidence_ids=[f"route-{origin}-{destination}"],
        )
        for origin, destination, minutes in case.edges
    ]
    return CandidatePlanningProblem(
        constraints=case.constraints,
        day_windows=[
            PlanningDayWindow(
                day=1,
                available_from=base + timedelta(hours=8),
                available_until=base + timedelta(hours=18),
                origin_place_id="hotel",
            )
        ],
        candidates=candidates,
        availability=availability,
        travel_times=travel_times,
        minimum_transfer_buffer_minutes=15,
    )


def run_candidate_planning_experiment(project_root: Path) -> dict[str, Any]:
    dataset_path = project_root / "evals/datasets/candidate_planning_seed.json"
    raw = dataset_path.read_bytes()
    cases = [CandidatePlanningCase.model_validate(item) for item in json.loads(raw.decode("utf-8"))]
    case_ids = [case.case_id for case in cases]
    if not cases or len(case_ids) != len(set(case_ids)):
        raise ValueError("candidate planning cases must be non-empty and uniquely identified")
    planner = ExplainableGreedyPlanner()
    outputs: list[dict[str, Any]] = []
    exact = 0
    safe_admissions = 0
    traced_candidates = 0
    total_candidates = 0

    for case in cases:
        result = planner.generate(_build_problem(case))
        selected = [item.place_id for day in result.itinerary.days for item in day.activities]
        skips = {
            item.place_id: item.reason_code for item in result.decisions if item.action == "skipped"
        }
        exact_match = (
            selected == case.expected_selected
            and result.unscheduled_required_places == case.expected_unscheduled_required
            and all(skips.get(key) == value for key, value in case.expected_skips.items())
        )
        exact += int(exact_match)
        unsafe_codes = {
            item.code
            for item in result.violations
            if item.code not in {"REQUIRED_PLACE_MISSING", "DAY_COUNT_MISMATCH"}
        }
        safe_admissions += int(not unsafe_codes)
        total_candidates += len(case.candidates)
        traced_candidates += len({item.place_id for item in result.decisions})
        outputs.append(
            {
                "case_id": case.case_id,
                "selected": selected,
                "skips": skips,
                "unscheduled_required": result.unscheduled_required_places,
                "violation_codes": sorted({item.code for item in result.violations}),
                "exact_match": exact_match,
            }
        )

    return {
        "experiment": "stage5b-explainable-greedy-candidate-planning",
        "algorithm": "explainable-greedy-v1",
        "dataset": str(dataset_path.relative_to(project_root)),
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "metrics": {
            "case_count": len(cases),
            "expected_outcome_exact_match": exact / len(cases),
            "unsafe_activity_admission_free_rate": safe_admissions / len(cases),
            "candidate_decision_trace_coverage": traced_candidates / total_candidates,
        },
        "limitations": [
            "Project-authored controlled fixtures, not independently reviewed traffic.",
            "Greedy selection is deterministic but does not prove global optimality.",
            "Travel times are static directed fixtures and do not model traffic uncertainty.",
        ],
        "cases": outputs,
    }
