from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from pydantic import BaseModel, Field

from travelmind.context.builder import build_context_items
from travelmind.context.coverage import infer_coverage_targets
from travelmind.context.models import ContextBudget, ContextBudgetError, ContextKind
from travelmind.context.pipeline import RefinedCoverageContextBuilder
from travelmind.observability import RunTelemetry, TelemetrySink
from travelmind.planner.candidates import (
    CandidatePlanningProblem,
    PlaceCandidate,
    PlanningDayWindow,
    PlanningDecision,
)
from travelmind.planner.llm_candidates import (
    CandidatePlanningStrategy,
    PlannerCall,
)
from travelmind.repair import build_itinerary_repair_graph
from travelmind.retrieval.base import Retriever
from travelmind.schemas import (
    ConstraintViolation,
    Itinerary,
    PlaceAvailability,
    PlanningValidationContext,
    TravelRequest,
    TravelTimeEstimate,
)


class EndToEndPlanningInput(BaseModel):
    request: TravelRequest
    day_windows: list[PlanningDayWindow]
    candidate_catalog: list[PlaceCandidate]
    availability: list[PlaceAvailability]
    travel_times: list[TravelTimeEstimate]
    non_activity_cost: float = Field(default=0, ge=0)
    minimum_transfer_buffer_minutes: int = Field(default=15, ge=0, le=180)


class EndToEndPlanningResult(BaseModel):
    status: str
    itinerary: Itinerary | None = None
    violations: list[ConstraintViolation] = Field(default_factory=list)
    decisions: list[PlanningDecision] = Field(default_factory=list)
    retrieved_evidence_count: int = 0
    packed_evidence_count: int = 0
    candidate_count: int = 0
    estimated_context_tokens: int = 0
    repair_attempts: int = 0
    modified_days: list[int] = Field(default_factory=list)
    planner_call: PlannerCall | None = None
    degraded_components: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    trace_id: str | None = None
    telemetry_degraded: bool = False


class EndToEndPlanningPipeline:
    """Compose retrieval, refined context, planning, validation, and bounded repair."""

    def __init__(
        self,
        *,
        retriever: Retriever,
        planning_strategy: CandidatePlanningStrategy,
        fallback_retriever: Retriever | None = None,
        aspects_by_document: dict[str, set[str]] | None = None,
        retrieval_limit: int = 10,
        max_repair_attempts: int = 2,
        telemetry_sink: TelemetrySink | None = None,
        trace_id_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        if retrieval_limit < 1:
            raise ValueError("retrieval_limit must be positive")
        if max_repair_attempts < 1:
            raise ValueError("max_repair_attempts must be positive")
        self._retriever = retriever
        self._fallback_retriever = fallback_retriever
        self._strategy = planning_strategy
        self._aspects = aspects_by_document or {}
        self._retrieval_limit = retrieval_limit
        self._max_repair_attempts = max_repair_attempts
        self._telemetry_sink = telemetry_sink
        self._trace_id_factory = trace_id_factory
        self._context_builder = RefinedCoverageContextBuilder(
            ContextBudget(
                max_context_tokens=768,
                reserved_output_tokens=192,
                safety_margin_tokens=64,
                max_tokens_per_evidence=160,
            )
        )

    def run(self, runtime_input: EndToEndPlanningInput) -> EndToEndPlanningResult:
        telemetry = RunTelemetry(self._trace_id_factory(), self._telemetry_sink)
        telemetry.emit(
            component="planning_pipeline",
            operation="run",
            status="started",
            attributes={"retrieval_limit": self._retrieval_limit},
        )

        def finish(**values) -> EndToEndPlanningResult:
            status = values["status"]
            telemetry.emit(
                component="planning_pipeline",
                operation="run",
                status="succeeded" if status == "completed" else "failed",
                reason_code="completed" if status == "completed" else "pipeline_failed",
                attributes={
                    "status": status,
                    "degraded_component_count": len(values.get("degraded_components", [])),
                    "violation_count": len(values.get("violations", [])),
                },
            )
            return EndToEndPlanningResult(
                **values,
                trace_id=telemetry.trace_id,
                telemetry_degraded=telemetry.degraded,
            )

        degraded: list[str] = []
        try:
            with telemetry.span(
                "retriever", "primary_search", retrieval_limit=self._retrieval_limit
            ) as span:
                diagnostic_search = getattr(self._retriever, "search_with_diagnostics", None)
                if callable(diagnostic_search):
                    retrieval = diagnostic_search(
                        [runtime_input.request.query], limit=self._retrieval_limit
                    )
                    evidence = retrieval.evidence
                    degraded.extend(retrieval.degraded_components)
                    span.attributes.update(
                        {
                            "fallback_used": retrieval.fallback_used,
                            "retrieval_mode": retrieval.mode,
                            "cache_age_seconds": retrieval.cache_age_seconds,
                            "circuit_state": retrieval.circuit.state,
                        }
                    )
                else:
                    evidence = self._retriever.search(
                        [runtime_input.request.query], limit=self._retrieval_limit
                    )
                span.attributes["evidence_count"] = len(evidence)
        except Exception:
            if self._fallback_retriever is None:
                return finish(
                    status="failed",
                    degraded_components=["retriever"],
                    failure_reason="Retrieval failed and no fallback was available.",
                )
            try:
                with telemetry.span(
                    "fallback_retriever",
                    "fallback_search",
                    retrieval_limit=self._retrieval_limit,
                    fallback_used=True,
                ) as span:
                    diagnostic_search = getattr(
                        self._fallback_retriever, "search_with_diagnostics", None
                    )
                    if callable(diagnostic_search):
                        retrieval = diagnostic_search(
                            [runtime_input.request.query], limit=self._retrieval_limit
                        )
                        evidence = retrieval.evidence
                        degraded.extend(retrieval.degraded_components)
                        span.attributes.update(
                            {
                                "retrieval_mode": retrieval.mode,
                                "cache_age_seconds": retrieval.cache_age_seconds,
                                "circuit_state": retrieval.circuit.state,
                            }
                        )
                    else:
                        evidence = self._fallback_retriever.search(
                            [runtime_input.request.query], limit=self._retrieval_limit
                        )
                    span.attributes["evidence_count"] = len(evidence)
            except Exception:
                return finish(
                    status="failed",
                    degraded_components=["retriever", "fallback_retriever"],
                    failure_reason="Both retrieval paths failed.",
                )
            degraded.append("retriever")

        enriched = []
        for item in evidence:
            document_id = str(item.metadata.get("document_id", item.id))
            aspects = self._aspects.get(document_id, set())
            metadata = dict(item.metadata)
            if aspects:
                metadata["aspects"] = ",".join(sorted(aspects))
            enriched.append(item.model_copy(update={"metadata": metadata}))
        try:
            with telemetry.span("context_builder", "build", evidence_count=len(enriched)) as span:
                refined = self._context_builder.build(
                    build_context_items(runtime_input.request, enriched),
                    infer_coverage_targets(runtime_input.request.query),
                )
                span.attributes["estimated_context_tokens"] = (
                    refined.packed.trace.estimated_input_tokens_after
                )
        except ContextBudgetError:
            return finish(
                status="failed",
                retrieved_evidence_count=len(enriched),
                degraded_components=degraded,
                failure_reason="Mandatory context exceeded the planning budget.",
            )

        score_by_place: dict[str, float] = {}
        evidence_by_place: dict[str, list[str]] = {}
        for item in enriched:
            place_id = str(item.metadata.get("place_id", ""))
            if not place_id:
                continue
            score_by_place[place_id] = max(score_by_place.get(place_id, 0), item.score)
            evidence_by_place.setdefault(place_id, []).append(item.id)
        if not score_by_place:
            return finish(
                status="failed",
                retrieved_evidence_count=len(enriched),
                degraded_components=degraded,
                failure_reason="Retrieval produced no place-linked evidence.",
            )
        maximum_score = max(score_by_place.values()) or 1
        candidates = [
            item.model_copy(
                update={
                    "relevance_score": max(
                        0.0, min(1.0, score_by_place[item.place_id] / maximum_score)
                    ),
                    "evidence_ids": list(dict.fromkeys(evidence_by_place[item.place_id])),
                }
            )
            for item in runtime_input.candidate_catalog
            if item.place_id in score_by_place
        ]
        if not candidates:
            return finish(
                status="failed",
                retrieved_evidence_count=len(enriched),
                degraded_components=degraded,
                failure_reason="No retrieved place matched the candidate catalog.",
            )
        problem = CandidatePlanningProblem(
            constraints=runtime_input.request.constraints,
            day_windows=runtime_input.day_windows,
            candidates=candidates,
            availability=runtime_input.availability,
            travel_times=runtime_input.travel_times,
            non_activity_cost=runtime_input.non_activity_cost,
            minimum_transfer_buffer_minutes=(runtime_input.minimum_transfer_buffer_minutes),
        )
        telemetry.emit(
            component="candidate_builder",
            operation="build",
            status="succeeded",
            attributes={"candidate_count": len(candidates)},
        )
        with telemetry.span("planner", "plan", candidate_count=len(candidates)) as planner_span:
            strategy_result = self._strategy.plan(
                problem,
                runtime_input.request,
                refined.packed.rendered,
            )
            planner_span.attributes["fallback_used"] = bool(
                strategy_result.call and strategy_result.call.fallback_used
            )
        planning = strategy_result.planning
        itinerary = planning.itinerary
        violations = planning.violations
        repair_attempts = 0
        modified_days: list[int] = []
        status = "completed" if not violations else "failed"
        failure_reason = None
        if violations:
            with telemetry.span(
                "itinerary_repair",
                "repair",
                violation_count=len(violations),
            ) as repair_span:
                repair = build_itinerary_repair_graph(
                    max_repair_attempts=self._max_repair_attempts
                ).invoke(
                    {
                        "itinerary": itinerary,
                        "constraints": runtime_input.request.constraints,
                        "context": PlanningValidationContext(
                            availability=problem.availability,
                            travel_times=problem.travel_times,
                            minimum_transfer_buffer_minutes=(
                                problem.minimum_transfer_buffer_minutes
                            ),
                        ),
                        "candidates": candidates,
                    }
                )
                repair_span.attributes["repair_attempts"] = repair["repair_attempts"]
                repair_span.attributes["violation_count"] = len(repair["violations"])
            itinerary = repair["itinerary"]
            violations = repair["violations"]
            repair_attempts = repair["repair_attempts"]
            modified_days = repair["modified_days"]
            status = repair["status"]
            failure_reason = repair["failure_reason"]

        packed_evidence = sum(item.kind == ContextKind.EVIDENCE for item in refined.packed.items)
        return finish(
            status=status,
            itinerary=itinerary,
            violations=violations,
            decisions=planning.decisions,
            retrieved_evidence_count=len(enriched),
            packed_evidence_count=packed_evidence,
            candidate_count=len(candidates),
            estimated_context_tokens=(refined.packed.trace.estimated_input_tokens_after),
            repair_attempts=repair_attempts,
            modified_days=modified_days,
            planner_call=strategy_result.call,
            degraded_components=list(dict.fromkeys(degraded)),
            failure_reason=failure_reason,
        )
