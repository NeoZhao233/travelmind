from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from travelmind.planner.constraints import validate_itinerary
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


def make_activity(name: str, start_hour: int, end_hour: int, cost: float = 0) -> Activity:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return Activity(
        place_id=name,
        name=name,
        start_at=base + timedelta(hours=start_hour),
        end_at=base + timedelta(hours=end_hour),
        estimated_cost=cost,
    )


def test_validator_detects_budget_overlap_required_and_excluded_places() -> None:
    itinerary = Itinerary(
        days=[
            DayPlan(
                day=1,
                activities=[
                    make_activity("A", 9, 12, 80),
                    make_activity("B", 11, 13, 70),
                ],
            )
        ],
        estimated_total_cost=150,
    )
    constraints = TravelConstraints(
        budget=100,
        required_places=["C"],
        excluded_places=["B"],
    )

    codes = {item.code for item in validate_itinerary(itinerary, constraints)}
    assert codes == {
        "BUDGET_EXCEEDED",
        "TIME_CONFLICT",
        "REQUIRED_PLACE_MISSING",
        "EXCLUDED_PLACE_PRESENT",
    }


def availability(
    place_id: str,
    *,
    status: str = "open",
    opens: int = 8,
    closes: int = 18,
    booking_required: bool | None = False,
    evidence_ids: list[str] | None = None,
    valid_until: datetime | None = None,
) -> PlaceAvailability:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    windows = []
    if status == "open":
        windows = [
            OperatingWindow(
                opens_at=base + timedelta(hours=opens),
                closes_at=base + timedelta(hours=closes),
            )
        ]
    return PlaceAvailability(
        place_id=place_id,
        service_date=base.date(),
        status=status,
        windows=windows,
        booking_required=booking_required,
        evidence_ids=["official-hours"] if evidence_ids is None else evidence_ids,
        valid_until=valid_until,
    )


def test_validator_recomputes_total_instead_of_trusting_claimed_cost() -> None:
    itinerary = Itinerary(
        days=[DayPlan(day=1, activities=[make_activity("A", 9, 10, 120)])],
        estimated_total_cost=20,
    )

    codes = {item.code for item in validate_itinerary(itinerary, TravelConstraints(budget=100))}

    assert codes == {"COST_TOTAL_MISMATCH", "BUDGET_EXCEEDED"}


def test_validator_detects_day_count_and_accepts_place_id_as_required() -> None:
    itinerary = Itinerary(
        days=[DayPlan(day=1, activities=[make_activity("A", 9, 10)])],
        estimated_total_cost=0,
    )

    violations = validate_itinerary(
        itinerary,
        TravelConstraints(days=2, required_places=["A"]),
    )

    assert [item.code for item in violations] == ["DAY_COUNT_MISMATCH"]


def test_validator_rejects_duplicate_or_nonsequential_day_indexes() -> None:
    itinerary = Itinerary(
        days=[DayPlan(day=1), DayPlan(day=1)],
        estimated_total_cost=0,
    )

    codes = {item.code for item in validate_itinerary(itinerary, TravelConstraints(days=2))}

    assert codes == {"DAY_COUNT_MISMATCH"}


def test_validator_accepts_adjacent_activities_as_half_open_intervals() -> None:
    itinerary = Itinerary(
        days=[
            DayPlan(
                day=1,
                activities=[make_activity("A", 9, 10), make_activity("B", 10, 11)],
            )
        ],
        estimated_total_cost=0,
    )

    assert validate_itinerary(itinerary, TravelConstraints()) == []


def test_validator_checks_evidence_hours_and_booking() -> None:
    activity = make_activity("A", 7, 10)
    activity.evidence_ids = ["doc-a"]
    itinerary = Itinerary(
        days=[DayPlan(day=1, activities=[activity])],
        estimated_total_cost=0,
    )
    context = PlanningValidationContext(
        availability=[availability("A", opens=8, booking_required=True)]
    )

    codes = {item.code for item in validate_itinerary(itinerary, TravelConstraints(), context)}

    assert codes == {"OUTSIDE_OPENING_HOURS"}

    activity.start_at = datetime(2026, 1, 1, 9, tzinfo=UTC)
    codes = {item.code for item in validate_itinerary(itinerary, TravelConstraints(), context)}
    assert codes == {"BOOKING_UNCONFIRMED"}

    activity.booking_status = "confirmed"
    assert validate_itinerary(itinerary, TravelConstraints(), context) == []


@pytest.mark.parametrize(
    ("records", "expected"),
    [
        ([], "AVAILABILITY_MISSING"),
        ([availability("A", status="unknown")], "AVAILABILITY_UNKNOWN"),
        ([availability("A", status="closed")], "PLACE_CLOSED"),
        ([availability("A", evidence_ids=[])], "AVAILABILITY_UNKNOWN"),
        (
            [
                availability(
                    "A",
                    valid_until=datetime(2025, 12, 31, 23, tzinfo=UTC),
                )
            ],
            "AVAILABILITY_STALE",
        ),
    ],
)
def test_validator_fails_closed_for_unusable_availability(
    records: list[PlaceAvailability], expected: str
) -> None:
    activity = make_activity("A", 9, 10)
    activity.evidence_ids = ["doc-a"]
    itinerary = Itinerary(
        days=[DayPlan(day=1, activities=[activity])],
        estimated_total_cost=0,
    )

    codes = {
        item.code
        for item in validate_itinerary(
            itinerary,
            TravelConstraints(),
            PlanningValidationContext(availability=records),
        )
    }

    assert expected in codes


def test_validator_can_explicitly_allow_missing_availability_for_legacy_mode() -> None:
    activity = make_activity("A", 9, 10)
    activity.evidence_ids = ["doc-a"]
    itinerary = Itinerary(
        days=[DayPlan(day=1, activities=[activity])],
        estimated_total_cost=0,
    )

    violations = validate_itinerary(
        itinerary,
        TravelConstraints(),
        PlanningValidationContext(fail_closed_on_missing_availability=False),
    )

    assert violations == []


def test_activity_and_operating_window_require_timezone_aware_datetimes() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Activity(
            place_id="A",
            name="A",
            start_at=datetime(2026, 1, 1, 9),
            end_at=datetime(2026, 1, 1, 10),
            estimated_cost=0,
        )


def test_validation_context_rejects_ambiguous_duplicate_availability() -> None:
    with pytest.raises(ValidationError, match="unique"):
        PlanningValidationContext(availability=[availability("A"), availability("A")])


def travel(origin: str, destination: str, minutes: int) -> TravelTimeEstimate:
    return TravelTimeEstimate(
        origin_place_id=origin,
        destination_place_id=destination,
        service_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
        status="known",
        duration_minutes=minutes,
        evidence_ids=[f"route-{origin}-{destination}"],
    )


def test_validator_checks_first_intermediate_and_return_travel_with_buffer() -> None:
    first = make_activity("A", 9, 10)
    second = make_activity("B", 10, 11)
    first.evidence_ids = ["doc-a"]
    second.evidence_ids = ["doc-b"]
    itinerary = Itinerary(
        days=[
            DayPlan(
                day=1,
                activities=[first, second],
                available_from=datetime(2026, 1, 1, 8, tzinfo=UTC),
                available_until=datetime(2026, 1, 1, 12, tzinfo=UTC),
                origin_place_id="hotel",
            )
        ],
        estimated_total_cost=0,
    )
    context = PlanningValidationContext(
        availability=[availability("A"), availability("B")],
        travel_times=[
            travel("hotel", "A", 30),
            travel("A", "B", 20),
            travel("B", "hotel", 30),
        ],
        minimum_transfer_buffer_minutes=10,
    )

    codes = {item.code for item in validate_itinerary(itinerary, TravelConstraints(), context)}

    assert codes == {"TRAVEL_TIME_INFEASIBLE"}


def test_validator_fails_closed_for_missing_travel_edge() -> None:
    activity = make_activity("A", 9, 10)
    activity.evidence_ids = ["doc-a"]
    itinerary = Itinerary(
        days=[
            DayPlan(
                day=1,
                activities=[activity],
                available_from=datetime(2026, 1, 1, 8, tzinfo=UTC),
                available_until=datetime(2026, 1, 1, 12, tzinfo=UTC),
                origin_place_id="hotel",
            )
        ],
        estimated_total_cost=0,
    )
    context = PlanningValidationContext(
        availability=[availability("A")],
        travel_times=[travel("hotel", "A", 30)],
    )

    codes = {item.code for item in validate_itinerary(itinerary, TravelConstraints(), context)}

    assert codes == {"TRAVEL_TIME_MISSING"}
