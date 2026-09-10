from typing import Literal, TypedDict

from travelmind.schemas import ConstraintViolation, Evidence, Itinerary, TravelRequest


class TravelAgentState(TypedDict, total=False):
    request: TravelRequest
    retrieval_queries: list[str]
    evidence: list[Evidence]
    itinerary: Itinerary | None
    violations: list[ConstraintViolation]
    retrieval_attempts: int
    status: Literal[
        "initialized",
        "retrieving",
        "insufficient_evidence",
        "generated",
        "completed",
        "failed",
    ]
    failure_reason: str | None
