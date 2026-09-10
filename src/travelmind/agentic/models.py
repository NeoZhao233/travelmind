from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class QueryIntent(StrEnum):
    SEMANTIC = "semantic"
    EXACT_FACT = "exact_fact"
    TEMPORAL = "temporal"
    MULTI_CONSTRAINT = "multi_constraint"
    GENERIC = "generic"


class RoutingDecision(BaseModel):
    intent: QueryIntent
    retrieval_strategy: Literal["hybrid"] = "hybrid"
    requires_structured_validation: bool = False
    should_decompose: bool = False
    reason_codes: list[str] = Field(default_factory=list)


class EvidenceAssessment(BaseModel):
    sufficient: bool
    coverage_score: float = Field(ge=0, le=1)
    required_aspects: list[str] = Field(default_factory=list)
    covered_aspects: list[str] = Field(default_factory=list)
    missing_aspects: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class TrajectoryEvent(BaseModel):
    node: str
    attempt: int = Field(ge=0)
    outcome: str
    reason_codes: list[str] = Field(default_factory=list)
    error_type: str | None = None
