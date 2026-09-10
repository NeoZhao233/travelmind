from __future__ import annotations

from travelmind.context.builder import CoverageAwareContextBuilder
from travelmind.context.models import (
    ContextBudget,
    ContextItem,
    RefinedPackedContext,
)
from travelmind.context.refinement import EvidenceRefiner
from travelmind.context.tokenization import TokenEstimator


class RefinedCoverageContextBuilder:
    """Compose Stage 4D refinement with Stage 4C selection and Stage 4B budgeting."""

    def __init__(
        self,
        budget: ContextBudget,
        *,
        refiner: EvidenceRefiner | None = None,
        estimator: TokenEstimator | None = None,
    ) -> None:
        self.refiner = refiner or EvidenceRefiner(estimator=estimator)
        self.packer = CoverageAwareContextBuilder(budget, estimator=estimator)

    def build(
        self,
        items: list[ContextItem],
        coverage_targets: set[str],
    ) -> RefinedPackedContext:
        refined = self.refiner.refine(items, coverage_targets)
        packed = self.packer.build(refined.items, coverage_targets)
        return RefinedPackedContext(packed=packed, refinement_trace=refined.trace)
