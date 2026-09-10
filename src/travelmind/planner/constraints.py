from datetime import date, datetime, timedelta

from travelmind.schemas import (
    Activity,
    ConstraintViolation,
    Itinerary,
    PlaceAvailability,
    PlanningValidationContext,
    TravelConstraints,
    TravelTimeEstimate,
)


def _availability_index(
    context: PlanningValidationContext,
) -> dict[tuple[str, date], PlaceAvailability]:
    return {(item.place_id, item.service_date): item for item in context.availability}


def _travel_index(
    context: PlanningValidationContext,
) -> dict[tuple[str, str, date], TravelTimeEstimate]:
    return {
        (item.origin_place_id, item.destination_place_id, item.service_date): item
        for item in context.travel_times
    }


def _validate_travel_leg(
    *,
    origin_place_id: str,
    destination_place_id: str,
    departure_at: datetime,
    must_arrive_by: datetime,
    affected_place_id: str,
    day: int,
    context: PlanningValidationContext,
    index: dict[tuple[str, str, date], TravelTimeEstimate],
) -> list[ConstraintViolation]:
    if origin_place_id == destination_place_id:
        return []
    estimate = index.get((origin_place_id, destination_place_id, departure_at.date()))
    common = {"day": day, "place_id": affected_place_id}
    if estimate is None:
        return [
            ConstraintViolation(
                code="TRAVEL_TIME_MISSING",
                message=f"No travel time from {origin_place_id} to {destination_place_id}.",
                **common,
            )
        ]
    if estimate.status == "unknown" or not estimate.evidence_ids:
        return [
            ConstraintViolation(
                code="TRAVEL_TIME_UNKNOWN",
                message=f"Travel time from {origin_place_id} to {destination_place_id} is unknown.",
                **common,
            )
        ]
    if estimate.valid_until is not None and departure_at > estimate.valid_until:
        return [
            ConstraintViolation(
                code="TRAVEL_TIME_STALE",
                message=f"Travel time from {origin_place_id} to {destination_place_id} is stale.",
                **common,
            )
        ]
    assert estimate.duration_minutes is not None
    earliest_arrival = departure_at + timedelta(
        minutes=(estimate.duration_minutes + context.minimum_transfer_buffer_minutes)
    )
    if earliest_arrival > must_arrive_by:
        return [
            ConstraintViolation(
                code="TRAVEL_TIME_INFEASIBLE",
                message=(
                    f"Travel from {origin_place_id} reaches {destination_place_id} "
                    f"after its scheduled boundary."
                ),
                **common,
            )
        ]
    return []


def _validate_availability(
    *,
    activity: Activity,
    day: int,
    context: PlanningValidationContext,
    index: dict[tuple[str, date], PlaceAvailability],
) -> list[ConstraintViolation]:
    service_date = activity.start_at.date()
    availability = index.get((activity.place_id, service_date))
    common = {"day": day, "place_id": activity.place_id}
    if availability is None:
        if not context.fail_closed_on_missing_availability:
            return []
        return [
            ConstraintViolation(
                code="AVAILABILITY_MISSING",
                message=f"No availability evidence for {activity.name} on {service_date}.",
                **common,
            )
        ]
    if not availability.evidence_ids:
        return [
            ConstraintViolation(
                code="AVAILABILITY_UNKNOWN",
                message=f"Availability for {activity.name} has no source evidence.",
                **common,
            )
        ]
    if availability.valid_until is not None and activity.start_at > availability.valid_until:
        return [
            ConstraintViolation(
                code="AVAILABILITY_STALE",
                message=f"Availability evidence for {activity.name} expires before the visit.",
                **common,
            )
        ]
    if availability.status == "unknown":
        return [
            ConstraintViolation(
                code="AVAILABILITY_UNKNOWN",
                message=f"Availability is unknown for {activity.name}.",
                **common,
            )
        ]
    if availability.status == "closed":
        return [
            ConstraintViolation(
                code="PLACE_CLOSED",
                message=f"{activity.name} is closed on {service_date}.",
                **common,
            )
        ]
    if not any(
        window.opens_at <= activity.start_at and activity.end_at <= window.closes_at
        for window in availability.windows
    ):
        return [
            ConstraintViolation(
                code="OUTSIDE_OPENING_HOURS",
                message=f"{activity.name} is not fully contained in an operating window.",
                **common,
            )
        ]
    if availability.booking_required and activity.booking_status != "confirmed":
        return [
            ConstraintViolation(
                code="BOOKING_UNCONFIRMED",
                message=f"{activity.name} requires a confirmed booking.",
                **common,
            )
        ]
    return []


def validate_itinerary(
    itinerary: Itinerary,
    constraints: TravelConstraints,
    context: PlanningValidationContext | None = None,
) -> list[ConstraintViolation]:
    violations: list[ConstraintViolation] = []

    computed_total = itinerary.non_activity_cost + sum(
        activity.estimated_cost for day in itinerary.days for activity in day.activities
    )
    if abs(computed_total - itinerary.estimated_total_cost) > 0.01:
        violations.append(
            ConstraintViolation(
                code="COST_TOTAL_MISMATCH",
                message=(
                    f"Claimed total {itinerary.estimated_total_cost:.2f} does not match "
                    f"recomputed total {computed_total:.2f}."
                ),
            )
        )
    if constraints.budget is not None and computed_total > constraints.budget:
        violations.append(
            ConstraintViolation(
                code="BUDGET_EXCEEDED",
                message=(
                    f"Recomputed cost {computed_total:.2f} exceeds budget {constraints.budget:.2f}."
                ),
            )
        )

    actual_day_numbers = [day.day for day in itinerary.days]
    expected_day_numbers = list(range(1, len(itinerary.days) + 1))
    wrong_count = constraints.days is not None and len(itinerary.days) != constraints.days
    invalid_numbering = actual_day_numbers != expected_day_numbers
    if wrong_count or invalid_numbering:
        requested = constraints.days if constraints.days is not None else len(itinerary.days)
        violations.append(
            ConstraintViolation(
                code="DAY_COUNT_MISMATCH",
                message=(
                    f"Itinerary day indexes are {actual_day_numbers}; "
                    f"expected sequential indexes for {requested} requested days."
                ),
            )
        )

    activity_identifiers = {
        identifier
        for day in itinerary.days
        for activity in day.activities
        for identifier in (activity.place_id, activity.name)
    }
    for place in constraints.required_places:
        if place not in activity_identifiers:
            violations.append(
                ConstraintViolation(
                    code="REQUIRED_PLACE_MISSING",
                    message=f"Required place is missing: {place}.",
                )
            )

    for place in constraints.excluded_places:
        if place in activity_identifiers:
            violations.append(
                ConstraintViolation(
                    code="EXCLUDED_PLACE_PRESENT",
                    message=f"Excluded place is present: {place}.",
                )
            )

    for day in itinerary.days:
        activities = sorted(day.activities, key=lambda activity: activity.start_at)
        for activity in activities:
            if (
                context is not None
                and context.require_activity_evidence
                and not activity.evidence_ids
            ):
                violations.append(
                    ConstraintViolation(
                        code="ACTIVITY_EVIDENCE_MISSING",
                        day=day.day,
                        place_id=activity.place_id,
                        message=f"Activity {activity.name} has no supporting evidence.",
                    )
                )
        for previous, current in zip(activities, activities[1:], strict=False):
            if current.start_at < previous.end_at:
                violations.append(
                    ConstraintViolation(
                        code="TIME_CONFLICT",
                        day=day.day,
                        place_id=current.place_id,
                        message=f"{previous.name} overlaps with {current.name}.",
                    )
                )

    if context is not None:
        index = _availability_index(context)
        for day in itinerary.days:
            for activity in day.activities:
                violations.extend(
                    _validate_availability(
                        activity=activity,
                        day=day.day,
                        context=context,
                        index=index,
                    )
                )

        travel_index = _travel_index(context)
        for day in itinerary.days:
            if (
                day.available_from is None
                or day.available_until is None
                or day.origin_place_id is None
            ):
                continue
            activities = sorted(day.activities, key=lambda item: item.start_at)
            for activity in activities:
                if activity.start_at < day.available_from or activity.end_at > day.available_until:
                    violations.append(
                        ConstraintViolation(
                            code="DAY_WINDOW_VIOLATION",
                            day=day.day,
                            place_id=activity.place_id,
                            message=f"{activity.name} falls outside the available day window.",
                        )
                    )
            if not activities:
                continue
            first = activities[0]
            violations.extend(
                _validate_travel_leg(
                    origin_place_id=day.origin_place_id,
                    destination_place_id=first.place_id,
                    departure_at=day.available_from,
                    must_arrive_by=first.start_at,
                    affected_place_id=first.place_id,
                    day=day.day,
                    context=context,
                    index=travel_index,
                )
            )
            for previous, current in zip(activities, activities[1:], strict=False):
                violations.extend(
                    _validate_travel_leg(
                        origin_place_id=previous.place_id,
                        destination_place_id=current.place_id,
                        departure_at=previous.end_at,
                        must_arrive_by=current.start_at,
                        affected_place_id=current.place_id,
                        day=day.day,
                        context=context,
                        index=travel_index,
                    )
                )
            last = activities[-1]
            violations.extend(
                _validate_travel_leg(
                    origin_place_id=last.place_id,
                    destination_place_id=day.origin_place_id,
                    departure_at=last.end_at,
                    must_arrive_by=day.available_until,
                    affected_place_id=last.place_id,
                    day=day.day,
                    context=context,
                    index=travel_index,
                )
            )

    return violations
