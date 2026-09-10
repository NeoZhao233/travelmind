from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class TravelConstraints(BaseModel):
    destination: str | None = None
    days: int | None = Field(default=None, ge=1, le=30)
    budget: float | None = Field(default=None, ge=0)
    pace: Literal["relaxed", "balanced", "intensive"] = "balanced"
    interests: list[str] = Field(default_factory=list)
    required_places: list[str] = Field(default_factory=list)
    excluded_places: list[str] = Field(default_factory=list)


class TravelRequest(BaseModel):
    query: str = Field(min_length=1)
    constraints: TravelConstraints = Field(default_factory=TravelConstraints)


class Evidence(BaseModel):
    id: str
    content: str
    source_url: str
    source_type: Literal["official", "guide", "structured", "realtime"]
    score: float
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class Activity(BaseModel):
    place_id: str
    name: str
    start_at: datetime
    end_at: datetime
    estimated_cost: float = Field(ge=0)
    evidence_ids: list[str] = Field(default_factory=list)
    booking_status: Literal["not_required", "confirmed", "unconfirmed", "unknown"] = "unknown"

    @model_validator(mode="after")
    def end_must_follow_start(self) -> Activity:
        if self.start_at.utcoffset() is None or self.end_at.utcoffset() is None:
            raise ValueError("activity timestamps must be timezone-aware")
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be later than start_at")
        return self


class DayPlan(BaseModel):
    day: int = Field(ge=1)
    activities: list[Activity] = Field(default_factory=list)
    available_from: datetime | None = None
    available_until: datetime | None = None
    origin_place_id: str | None = None

    @model_validator(mode="after")
    def validate_day_window(self) -> DayPlan:
        window_fields = (
            self.available_from,
            self.available_until,
            self.origin_place_id,
        )
        if all(value is None for value in window_fields):
            return self
        if any(value is None for value in window_fields):
            raise ValueError("day window requires from, until, and origin_place_id")
        assert self.available_from is not None
        assert self.available_until is not None
        if self.available_from.utcoffset() is None or self.available_until.utcoffset() is None:
            raise ValueError("day-window timestamps must be timezone-aware")
        if self.available_until <= self.available_from:
            raise ValueError("available_until must be later than available_from")
        return self


class Itinerary(BaseModel):
    days: list[DayPlan] = Field(default_factory=list)
    estimated_total_cost: float = Field(ge=0)
    non_activity_cost: float = Field(default=0, ge=0)
    assumptions: list[str] = Field(default_factory=list)


class OperatingWindow(BaseModel):
    """A half-open interval: an activity may end exactly when the window closes."""

    opens_at: datetime
    closes_at: datetime

    @model_validator(mode="after")
    def validate_window(self) -> OperatingWindow:
        if self.opens_at.utcoffset() is None or self.closes_at.utcoffset() is None:
            raise ValueError("operating-window timestamps must be timezone-aware")
        if self.closes_at <= self.opens_at:
            raise ValueError("closes_at must be later than opens_at")
        return self


class PlaceAvailability(BaseModel):
    """Time-bounded operational evidence for one place on one local service date."""

    place_id: str = Field(min_length=1)
    service_date: date
    status: Literal["open", "closed", "unknown"]
    windows: list[OperatingWindow] = Field(default_factory=list)
    booking_required: bool | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def status_matches_windows(self) -> PlaceAvailability:
        if self.status == "open" and not self.windows:
            raise ValueError("open availability requires at least one operating window")
        if self.status != "open" and self.windows:
            raise ValueError("closed or unknown availability cannot contain operating windows")
        if self.valid_until is not None and self.valid_until.utcoffset() is None:
            raise ValueError("valid_until must be timezone-aware")
        return self


class TravelTimeEstimate(BaseModel):
    """A sourced directed travel-time edge for one service date."""

    origin_place_id: str = Field(min_length=1)
    destination_place_id: str = Field(min_length=1)
    service_date: date
    status: Literal["known", "unknown"]
    duration_minutes: int | None = Field(default=None, ge=0)
    evidence_ids: list[str] = Field(default_factory=list)
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def status_matches_duration(self) -> TravelTimeEstimate:
        if self.status == "known" and self.duration_minutes is None:
            raise ValueError("known travel time requires duration_minutes")
        if self.status == "unknown" and self.duration_minutes is not None:
            raise ValueError("unknown travel time cannot contain duration_minutes")
        if self.valid_until is not None and self.valid_until.utcoffset() is None:
            raise ValueError("travel valid_until must be timezone-aware")
        return self


class PlanningValidationContext(BaseModel):
    """External facts and policy switches used by the hard-constraint validator."""

    availability: list[PlaceAvailability] = Field(default_factory=list)
    travel_times: list[TravelTimeEstimate] = Field(default_factory=list)
    require_activity_evidence: bool = True
    fail_closed_on_missing_availability: bool = True
    minimum_transfer_buffer_minutes: int = Field(default=0, ge=0, le=180)

    @model_validator(mode="after")
    def availability_keys_are_unique(self) -> PlanningValidationContext:
        keys = [(item.place_id, item.service_date) for item in self.availability]
        if len(keys) != len(set(keys)):
            raise ValueError("availability must be unique by place_id and service_date")
        travel_keys = [
            (item.origin_place_id, item.destination_place_id, item.service_date)
            for item in self.travel_times
        ]
        if len(travel_keys) != len(set(travel_keys)):
            raise ValueError("travel_times must be unique by origin, destination, and service_date")
        return self


class ConstraintViolation(BaseModel):
    code: Literal[
        "BUDGET_EXCEEDED",
        "TIME_CONFLICT",
        "REQUIRED_PLACE_MISSING",
        "EXCLUDED_PLACE_PRESENT",
        "DAY_COUNT_MISMATCH",
        "COST_TOTAL_MISMATCH",
        "ACTIVITY_EVIDENCE_MISSING",
        "AVAILABILITY_MISSING",
        "AVAILABILITY_UNKNOWN",
        "AVAILABILITY_STALE",
        "PLACE_CLOSED",
        "OUTSIDE_OPENING_HOURS",
        "BOOKING_UNCONFIRMED",
        "DAY_WINDOW_VIOLATION",
        "TRAVEL_TIME_MISSING",
        "TRAVEL_TIME_UNKNOWN",
        "TRAVEL_TIME_STALE",
        "TRAVEL_TIME_INFEASIBLE",
    ]
    message: str
    day: int | None = None
    place_id: str | None = None
