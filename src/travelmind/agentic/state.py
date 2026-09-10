from typing import Literal, TypedDict

from travelmind.agentic.models import EvidenceAssessment, RoutingDecision, TrajectoryEvent
from travelmind.schemas import ConstraintViolation, Evidence, Itinerary, TravelRequest


class AgenticTravelState(TypedDict, total=False):
    request: TravelRequest
    routing_decision: RoutingDecision
    retrieval_queries: list[str]
    evidence: list[Evidence]
    evidence_assessment: EvidenceAssessment
    itinerary: Itinerary | None
    violations: list[ConstraintViolation]
    retrieval_attempts: int
    rewrite_attempts: int
    trajectory: list[TrajectoryEvent]
    degraded_components: list[str]
    dependency_errors: list[dict[str, str]]
    status: Literal[
        "initialized",
        "routing",
        "retrieving",
        "grading",
        "rewriting",
        "generated",
        "completed",
        "failed",
    ]
    failure_reason: str | None
