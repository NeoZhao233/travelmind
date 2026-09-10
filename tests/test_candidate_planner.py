from datetime import UTC, date, datetime, timedelta

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

SERVICE_DATE = date(2026, 1, 1)
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def availability(place_id: str, *, booking_required: bool = False) -> PlaceAvailability:
    return PlaceAvailability(
        place_id=place_id,
        service_date=SERVICE_DATE,
        status="open",
        windows=[
            OperatingWindow(
                opens_at=BASE + timedelta(hours=8),
                closes_at=BASE + timedelta(hours=18),
            )
        ],
        booking_required=booking_required,
        evidence_ids=[f"hours-{place_id}"],
    )


def travel(origin: str, destination: str, minutes: int) -> TravelTimeEstimate:
    return TravelTimeEstimate(
        origin_place_id=origin,
        destination_place_id=destination,
        service_date=SERVICE_DATE,
        status="known",
        duration_minutes=minutes,
        evidence_ids=[f"route-{origin}-{destination}"],
    )


def base_problem() -> CandidatePlanningProblem:
    return CandidatePlanningProblem(
        constraints=TravelConstraints(
            days=1,
            budget=200,
            pace="relaxed",
            interests=["history"],
            required_places=["museum"],
            excluded_places=["bar"],
        ),
        day_windows=[
            PlanningDayWindow(
                day=1,
                available_from=BASE + timedelta(hours=8),
                available_until=BASE + timedelta(hours=18),
                origin_place_id="hotel",
            )
        ],
        candidates=[
            PlaceCandidate(
                place_id="museum",
                name="Museum",
                duration_minutes=120,
                estimated_cost=60,
                relevance_score=0.7,
                interest_tags=["history"],
                evidence_ids=["doc-museum"],
                booking_status="confirmed",
            ),
            PlaceCandidate(
                place_id="park",
                name="Park",
                duration_minutes=90,
                estimated_cost=10,
                relevance_score=0.9,
                interest_tags=["nature"],
                evidence_ids=["doc-park"],
                booking_status="not_required",
            ),
            PlaceCandidate(
                place_id="bar",
                name="Bar",
                duration_minutes=60,
                estimated_cost=30,
                relevance_score=1,
                evidence_ids=["doc-bar"],
            ),
        ],
        availability=[availability("museum", booking_required=True), availability("park")],
        travel_times=[
            travel("hotel", "museum", 30),
            travel("museum", "hotel", 30),
            travel("hotel", "park", 20),
            travel("park", "hotel", 20),
            travel("museum", "park", 25),
            travel("park", "museum", 25),
        ],
        minimum_transfer_buffer_minutes=15,
    )


def test_greedy_planner_prioritizes_required_then_utility_and_explains_choices() -> None:
    result = ExplainableGreedyPlanner().generate(base_problem())

    assert [item.place_id for item in result.itinerary.days[0].activities] == [
        "museum",
        "park",
    ]
    assert result.itinerary.estimated_total_cost == 70
    assert result.unscheduled_required_places == []
    assert result.violations == []
    reasons = {item.place_id: item.reason_code for item in result.decisions}
    assert reasons == {
        "bar": "excluded_by_request",
        "museum": "selected_required",
        "park": "selected_highest_utility",
    }
    selected = next(item for item in result.decisions if item.place_id == "museum")
    assert selected.score_components["required_bonus"] == 1000
    assert selected.score_components["interest_match"] == 20


def test_greedy_planner_fails_closed_when_route_is_missing() -> None:
    problem = base_problem()
    problem.travel_times = [
        edge for edge in problem.travel_times if edge.destination_place_id != "museum"
    ]

    result = ExplainableGreedyPlanner().generate(problem)

    assert "museum" not in {item.place_id for item in result.itinerary.days[0].activities}
    assert result.unscheduled_required_places == ["museum"]
    assert {item.code for item in result.violations} == {"REQUIRED_PLACE_MISSING"}
    museum = next(item for item in result.decisions if item.place_id == "museum")
    assert museum.reason_code == "inbound_travel_unavailable"


def test_greedy_planner_respects_recomputed_budget() -> None:
    problem = base_problem()
    problem.constraints.budget = 65

    result = ExplainableGreedyPlanner().generate(problem)

    assert [item.place_id for item in result.itinerary.days[0].activities] == ["museum"]
    park = next(item for item in result.decisions if item.place_id == "park")
    assert park.reason_code == "budget_exceeded"
    assert result.violations == []
