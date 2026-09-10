from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class StepKind(StrEnum):
    RETRIEVE = "retrieve"
    CHECK_AVAILABILITY = "check_availability"
    CHECK_BOOKING = "check_booking"
    ESTIMATE_TRAVEL_TIME = "estimate_travel_time"


class StepStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ToolOutcome(StrEnum):
    SUCCESS = "success"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    TRANSIENT_ERROR = "transient_error"
    PERMANENT_ERROR = "permanent_error"
    INVALID_OUTPUT = "invalid_output"


class FailureLayer(StrEnum):
    RETRIEVAL = "retrieval"
    TOOL = "tool"
    GENERATION = "generation"
    VALIDATION = "validation"
    ORCHESTRATION = "orchestration"


class RuntimeStep(BaseModel):
    step_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    kind: StepKind
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    outcome_code: str | None = None


class ExecutionPlan(BaseModel):
    plan_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    goal: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    steps: list[RuntimeStep] = Field(min_length=1)

    @model_validator(mode="after")
    def dependencies_are_valid(self) -> ExecutionPlan:
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("runtime step ids must be unique")
        known: set[str] = set()
        for step in self.steps:
            if step.step_id in step.depends_on:
                raise ValueError("runtime step cannot depend on itself")
            if not set(step.depends_on).issubset(known):
                raise ValueError("runtime dependencies must reference earlier steps")
            known.add(step.step_id)
        return self


class ToolObservation(BaseModel):
    call_id: str
    step_id: str
    tool_name: str
    outcome: ToolOutcome
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    error_type: str | None = None
    observed_at: datetime
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def timestamps_are_aware(self) -> ToolObservation:
        if self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.valid_until is not None and self.valid_until.utcoffset() is None:
            raise ValueError("valid_until must be timezone-aware")
        return self


class ToolResponse(BaseModel):
    outcome: ToolOutcome = ToolOutcome.SUCCESS
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def valid_until_is_aware(self) -> ToolResponse:
        if self.valid_until is not None and self.valid_until.utcoffset() is None:
            raise ValueError("valid_until must be timezone-aware")
        return self


class GroundingIssue(BaseModel):
    code: str
    message: str
    place_id: str | None = None
    evidence_id: str | None = None


class FailureAttribution(BaseModel):
    primary_layer: FailureLayer
    reason_code: str
    related_step_id: str | None = None
    related_tool: str | None = None
    related_evidence_ids: list[str] = Field(default_factory=list)
    contributing_reason_codes: list[str] = Field(default_factory=list)
