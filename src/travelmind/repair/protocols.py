from typing import Protocol

from travelmind.repair.models import RepairOutcome, RepairRequest


class ItineraryRepairer(Protocol):
    def repair(self, request: RepairRequest) -> RepairOutcome: ...
