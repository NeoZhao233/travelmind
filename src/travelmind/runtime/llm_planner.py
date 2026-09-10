from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from travelmind.agentic.llm_provider import LLMOutputError, StructuredLLMProvider
from travelmind.runtime.models import (
    ExecutionPlan,
    FailureAttribution,
    RuntimeStep,
    StepKind,
    ToolObservation,
)
from travelmind.runtime.protocols import RuntimePlanner
from travelmind.schemas import TravelRequest

RUNTIME_PLANNER_PROMPT_VERSION = "runtime-planner-v2-exact-tool-contracts"


class RuntimePlannerCall(BaseModel):
    prompt_version: str = RUNTIME_PLANNER_PROMPT_VERSION
    candidate_success: bool
    fallback_used: bool
    model: str | None = None
    latency_ms: float | None = None
    total_tokens: int = 0
    error_type: str | None = None
    reason_code: str | None = None
    normalized_step_count: int = Field(default=0, ge=0)


class RuntimePlannerTelemetry:
    def __init__(self) -> None:
        self.calls: list[RuntimePlannerCall] = []


class _PlanOutput(BaseModel):
    reason: str = Field(min_length=1, max_length=240)
    steps: list[RuntimeStep] = Field(min_length=1, max_length=6)


class RuntimePlanValidationError(LLMOutputError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class LLMRuntimePlanner:
    """Structured LLM plan candidate with deterministic fallback and strict action scope."""

    _TOOL_FOR_KIND = {
        StepKind.RETRIEVE: "candidate_search",
        StepKind.CHECK_AVAILABILITY: "availability",
        StepKind.CHECK_BOOKING: "booking",
        StepKind.ESTIMATE_TRAVEL_TIME: "travel_time",
    }

    def __init__(
        self,
        provider: StructuredLLMProvider,
        fallback: RuntimePlanner,
        *,
        allowed_place_ids: set[str],
        origin_place_id: str,
        primary_place_id: str,
        fallback_place_id: str,
        telemetry: RuntimePlannerTelemetry | None = None,
    ) -> None:
        if not allowed_place_ids:
            raise ValueError("allowed_place_ids must not be empty")
        self.provider = provider
        self.fallback = fallback
        self.allowed_place_ids = set(allowed_place_ids)
        self.origin_place_id = origin_place_id
        if {primary_place_id, fallback_place_id} - self.allowed_place_ids:
            raise ValueError("primary and fallback places must be allowlisted")
        self.primary_place_id = primary_place_id
        self.fallback_place_id = fallback_place_id
        self.telemetry = telemetry or RuntimePlannerTelemetry()

    def plan(
        self,
        request: TravelRequest,
        *,
        observations: list[ToolObservation],
        previous_plan: ExecutionPlan | None,
        failure: FailureAttribution | None,
    ) -> ExecutionPlan:
        result = None
        normalized_count = 0
        try:
            result = self.provider.complete_json(
                system_prompt=self._system_prompt(),
                user_prompt=json.dumps(
                    self._payload(request, observations, previous_plan, failure),
                    ensure_ascii=False,
                ),
                max_tokens=900,
            )
            output = _PlanOutput.model_validate(result.data)
            steps = self._normalize_reused_dependencies(output.steps, observations)
            steps, normalized_count = self._canonicalize_runtime_owned_arguments(
                steps, request
            )
            self._validate_action_scope(steps, request)
            revision = 1 if previous_plan is None else previous_plan.revision + 1
            plan = ExecutionPlan(
                plan_id=(previous_plan.plan_id if previous_plan else "llm-runtime-travel-plan"),
                revision=revision,
                goal=(previous_plan.goal if previous_plan else request.query),
                reason=output.reason,
                steps=steps,
            )
        except Exception as exc:
            if isinstance(exc, RuntimePlanValidationError):
                reason_code = exc.reason_code
            elif isinstance(exc, ValidationError):
                reason_code = "SCHEMA_VALIDATION_FAILED"
            elif result is None:
                reason_code = "PROVIDER_OR_ENVELOPE_FAILED"
            else:
                reason_code = "PLAN_CONSTRUCTION_FAILED"
            self.telemetry.calls.append(
                RuntimePlannerCall(
                    candidate_success=False,
                    fallback_used=True,
                    model=result.model if result else None,
                    latency_ms=result.latency_ms if result else None,
                    total_tokens=result.usage.total_tokens if result else 0,
                    error_type=type(exc).__name__,
                    reason_code=reason_code,
                    normalized_step_count=normalized_count,
                )
            )
            return self.fallback.plan(
                request,
                observations=observations,
                previous_plan=previous_plan,
                failure=failure,
            )
        self.telemetry.calls.append(
            RuntimePlannerCall(
                candidate_success=True,
                fallback_used=False,
                model=result.model,
                latency_ms=result.latency_ms,
                total_tokens=result.usage.total_tokens,
                normalized_step_count=normalized_count,
            )
        )
        return plan

    def _validate_action_scope(self, steps: list[RuntimeStep], request: TravelRequest) -> None:
        for step in steps:
            if step.tool_name != self._TOOL_FOR_KIND[step.kind]:
                raise RuntimePlanValidationError("TOOL_KIND_MISMATCH")
            if step.status != "pending" or step.attempts != 0 or step.outcome_code is not None:
                raise RuntimePlanValidationError("EXECUTION_STATE_FORGED")
            if step.kind == StepKind.RETRIEVE:
                if step.arguments != {"query": request.query}:
                    raise RuntimePlanValidationError("RETRIEVAL_ARGUMENTS_INVALID")
                continue
            if step.kind in {StepKind.CHECK_AVAILABILITY, StepKind.CHECK_BOOKING}:
                if set(step.arguments) != {"place_id"}:
                    raise RuntimePlanValidationError("PLACE_ARGUMENTS_INVALID")
                if step.arguments["place_id"] not in self.allowed_place_ids:
                    raise RuntimePlanValidationError("PLACE_NOT_ALLOWLISTED")
                continue
            expected_keys = {"origin_place_id", "destination_place_id"}
            if set(step.arguments) != expected_keys:
                raise RuntimePlanValidationError("TRAVEL_ARGUMENTS_INVALID")
            if step.arguments["origin_place_id"] != self.origin_place_id:
                raise RuntimePlanValidationError("TRAVEL_ORIGIN_CHANGED")
            if step.arguments["destination_place_id"] not in self.allowed_place_ids:
                raise RuntimePlanValidationError("DESTINATION_NOT_ALLOWLISTED")

    def _normalize_reused_dependencies(
        self,
        steps: list[RuntimeStep],
        observations: list[ToolObservation],
    ) -> list[RuntimeStep]:
        completed = {item.step_id for item in observations if item.outcome == "success"}
        normalized = [step.model_copy(deep=True) for step in steps]
        for step in normalized:
            step.depends_on = [
                identity for identity in step.depends_on if identity not in completed
            ]
        return normalized

    def _canonicalize_runtime_owned_arguments(
        self,
        steps: list[RuntimeStep],
        request: TravelRequest,
    ) -> tuple[list[RuntimeStep], int]:
        normalized = [step.model_copy(deep=True) for step in steps]
        changed = 0
        for step in normalized:
            before = step.arguments
            if step.kind == StepKind.RETRIEVE:
                step.arguments = {"query": request.query}
            elif step.kind in {StepKind.CHECK_AVAILABILITY, StepKind.CHECK_BOOKING}:
                if "place_id" in before:
                    step.arguments = {"place_id": before["place_id"]}
            elif "destination_place_id" in before:
                step.arguments = {
                    "origin_place_id": self.origin_place_id,
                    "destination_place_id": before["destination_place_id"],
                }
            changed += int(step.arguments != before)
        return normalized, changed

    def _payload(
        self,
        request: TravelRequest,
        observations: list[ToolObservation],
        previous_plan: ExecutionPlan | None,
        failure: FailureAttribution | None,
    ) -> dict[str, Any]:
        safe_observations = [
            {
                "step_id": item.step_id,
                "tool_name": item.tool_name,
                "outcome": item.outcome.value,
                "payload": item.payload if item.outcome == "success" else {},
                "evidence_ids": item.evidence_ids if item.outcome == "success" else [],
                "error_type": item.error_type,
            }
            for item in observations[-12:]
        ]
        return {
            "query": request.query,
            "constraints": request.constraints.model_dump(mode="json"),
            "allowed_place_ids": sorted(self.allowed_place_ids),
            "origin_place_id": self.origin_place_id,
            "primary_place_id": self.primary_place_id,
            "fallback_place_id": self.fallback_place_id,
            "booking_required": {
                self.primary_place_id: True,
                self.fallback_place_id: False,
            },
            "previous_plan": previous_plan.model_dump(mode="json") if previous_plan else None,
            "observations": safe_observations,
            "failure": failure.model_dump(mode="json") if failure else None,
        }

    def _system_prompt(self) -> str:
        return (
            "Return JSON only with schema: "
            '{"reason":"short explanation","steps":[{"step_id":"lowercase_id",'
            '"kind":"retrieve|check_availability|check_booking|estimate_travel_time",'
            '"tool_name":"candidate_search|availability|booking|travel_time",'
            '"arguments":{},"depends_on":[]}]}. '
            "Use only allowed place IDs and the supplied origin. Initial plans should search "
            "candidates, check availability and booking when relevant, then check travel time. "
            "After failure, reuse successful observations and include only necessary remaining "
            "steps. Argument contracts are exact: candidate_search takes only query copied "
            "exactly; "
            "availability and booking take only place_id; travel_time takes only origin_place_id "
            "and destination_place_id. depends_on may reference only steps in the returned "
            "revision, not a completed prior step. Follow booking_required. Prefer "
            "primary_place_id initially "
            "and fallback_place_id after a primary-path failure. Never change the user goal or "
            "invent completed state."
        )
