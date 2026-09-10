from typing import Protocol

from travelmind.schemas import Evidence, Itinerary, TravelRequest


class Planner(Protocol):
    def generate(self, request: TravelRequest, evidence: list[Evidence]) -> Itinerary: ...
