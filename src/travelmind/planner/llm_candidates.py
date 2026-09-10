from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from travelmind.agentic.llm_provider import (
    LLMOutputError,
    StructuredLLMProvider,
)
from travelmind.planner.candidates import (
    CandidatePlanningProblem,
    CandidatePlanningResult,
    ExplainableGreedyPlanner,
)
from travelmind.schemas import TravelRequest

PLANNER_PROMPT_VERSION = "candidate-ranker-v2-safe-shortlist"


class PlannerCall(BaseModel):
    component: str = "candidate_ranker"
    prompt_version: str = PLANNER_PROMPT_VERSION
    success: bool
    fallback_used: bool
    model: str | None = None
    latency_ms: float | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    provider_attempts: int = 0
    error_type: str | None = None
    error_reason_code: str | None = None
    expected_candidate_count: int | None = None
    returned_candidate_count: int | None = None
    missing_candidate_count: int | None = None
    unknown_candidate_count: int | None = None


class PlanningStrategyResult(BaseModel):
    planning: CandidatePlanningResult
    call: PlannerCall | None = None


class CandidatePlanningStrategy(Protocol):
    def plan(
        self,
        problem: CandidatePlanningProblem,
        request: TravelRequest,
        rendered_context: str,
    ) -> PlanningStrategyResult: ...


class DeterministicPlanningStrategy:
    def __init__(self, planner: ExplainableGreedyPlanner | None = None) -> None:
        self._planner = planner or ExplainableGreedyPlanner()

    def plan(
        self,
        problem: CandidatePlanningProblem,
        request: TravelRequest,
        rendered_context: str,
    ) -> PlanningStrategyResult:
        del request, rendered_context
        return PlanningStrategyResult(planning=self._planner.generate(problem))


class _RankedCandidateOutput(BaseModel):
    ranked_place_ids: list[str] = Field(min_length=1)
    reason_codes: list[str] = Field(default_factory=list, max_length=8)


class DeepSeekRankedPlanningStrategy:
    """Use an LLM for soft candidate ranking; deterministic code still owns feasibility."""

    def __init__(
        self,
        provider: StructuredLLMProvider,
        fallback: ExplainableGreedyPlanner | None = None,
    ) -> None:
        self._provider = provider
        self._fallback = fallback or ExplainableGreedyPlanner()

    def plan(
        self,
        problem: CandidatePlanningProblem,
        request: TravelRequest,
        rendered_context: str,
    ) -> PlanningStrategyResult:
        payload: dict[str, Any] = {
            "query": request.query,
            "constraints": request.constraints.model_dump(mode="json"),
            "candidates": [
                {
                    "place_id": item.place_id,
                    "name": item.name,
                    "duration_minutes": item.duration_minutes,
                    "estimated_cost": item.estimated_cost,
                    "retrieval_relevance": item.relevance_score,
                    "interest_tags": item.interest_tags,
                }
                for item in problem.candidates
            ],
            "evidence_context": rendered_context,
        }
        result = None
        expected_ids = [item.place_id for item in problem.candidates]
        returned_ids: list[str] | None = None
        error_reason = "provider_failure"
        try:
            result = self._provider.complete_json(
                system_prompt=(
                    "Return one JSON object only. Return an ordered shortlist of supplied "
                    "candidate "
                    "IDs for the user's stated soft preferences. You may omit unsuitable places. "
                    "Never repeat or invent IDs, facts, opening hours, costs, or routes. Hard "
                    "feasibility and omitted-candidate handling are deterministic. "
                    'Schema: {"ranked_place_ids":["id"],"reason_codes":["short_code"]}.'
                ),
                user_prompt=json.dumps(payload, ensure_ascii=False),
                max_tokens=320,
            )
            try:
                output = _RankedCandidateOutput.model_validate(result.data)
            except ValidationError as exc:
                error_reason = "schema_validation_failed"
                raise LLMOutputError("Planner ranking failed schema validation") from exc
            returned_ids = output.ranked_place_ids
            if len(output.ranked_place_ids) != len(set(output.ranked_place_ids)) or not set(
                output.ranked_place_ids
            ) <= set(expected_ids):
                error_reason = "candidate_set_mismatch"
                raise LLMOutputError(
                    "Planner shortlist contains duplicate or unknown candidate IDs"
                )
            original_order = [
                item.place_id
                for item in sorted(
                    problem.candidates,
                    key=lambda item: (-item.relevance_score, item.place_id),
                )
            ]
            full_order = [
                *output.ranked_place_ids,
                *[
                    place_id
                    for place_id in original_order
                    if place_id not in set(output.ranked_place_ids)
                ],
            ]
            rank_by_id = {place_id: rank for rank, place_id in enumerate(full_order)}
            count = len(full_order)
            reranked = [
                item.model_copy(
                    update={"relevance_score": (count - rank_by_id[item.place_id]) / count}
                )
                for item in problem.candidates
            ]
            planning = self._fallback.generate(
                problem.model_copy(update={"candidates": reranked}, deep=True)
            )
            call = PlannerCall(
                success=True,
                fallback_used=False,
                model=result.model,
                latency_ms=result.latency_ms,
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                total_tokens=result.usage.total_tokens,
                provider_attempts=result.provider_attempts,
                expected_candidate_count=len(expected_ids),
                returned_candidate_count=len(returned_ids),
                missing_candidate_count=len(set(expected_ids) - set(returned_ids)),
                unknown_candidate_count=0,
            )
            return PlanningStrategyResult(planning=planning, call=call)
        except Exception as exc:
            planning = self._fallback.generate(problem)
            returned_set = set(returned_ids or [])
            return PlanningStrategyResult(
                planning=planning,
                call=PlannerCall(
                    success=False,
                    fallback_used=True,
                    model=result.model if result is not None else None,
                    latency_ms=result.latency_ms if result is not None else None,
                    prompt_tokens=(result.usage.prompt_tokens if result is not None else 0),
                    completion_tokens=(result.usage.completion_tokens if result is not None else 0),
                    total_tokens=result.usage.total_tokens if result is not None else 0,
                    provider_attempts=(result.provider_attempts if result is not None else 0),
                    error_type=type(exc).__name__,
                    error_reason_code=error_reason,
                    expected_candidate_count=len(expected_ids),
                    returned_candidate_count=(
                        len(returned_ids) if returned_ids is not None else None
                    ),
                    missing_candidate_count=(
                        len(set(expected_ids) - returned_set) if returned_ids is not None else None
                    ),
                    unknown_candidate_count=(
                        len(returned_set - set(expected_ids)) if returned_ids is not None else None
                    ),
                ),
            )
