from typing import Protocol

from travelmind.agentic.models import EvidenceAssessment, RoutingDecision
from travelmind.schemas import Evidence, TravelRequest


class QueryRouter(Protocol):
    def route(self, request: TravelRequest) -> RoutingDecision: ...


class EvidenceGrader(Protocol):
    def grade(
        self,
        request: TravelRequest,
        evidence: list[Evidence],
    ) -> EvidenceAssessment: ...


class QueryRewriter(Protocol):
    def rewrite(
        self,
        request: TravelRequest,
        previous_queries: list[str],
        assessment: EvidenceAssessment,
        *,
        attempt: int,
    ) -> list[str]: ...
