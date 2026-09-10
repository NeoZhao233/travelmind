from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from travelmind.agentic.models import QueryIntent


class DatasetSplit(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"


class RoutingLabel(BaseModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    retrieval_query_id: str
    expected_intent: QueryIntent
    split: DatasetSplit
    rationale: str = Field(min_length=1)
    annotator: str = Field(min_length=1)
    reviewed: bool = False


class EvidenceGradingLabel(BaseModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    query: str = Field(min_length=2)
    evidence_document_ids: list[str]
    expected_sufficient: bool
    expected_required_aspects: list[str] = Field(default_factory=list)
    expected_missing_aspects: list[str] = Field(default_factory=list)
    split: DatasetSplit
    rationale: str = Field(min_length=1)
    annotator: str = Field(min_length=1)
    reviewed: bool = False

    @model_validator(mode="after")
    def sufficient_cases_have_no_missing_aspects(self) -> "EvidenceGradingLabel":
        if self.expected_sufficient and self.expected_missing_aspects:
            raise ValueError("Sufficient evidence cannot have expected missing aspects")
        unknown = set(self.expected_missing_aspects) - set(self.expected_required_aspects)
        if unknown:
            raise ValueError(f"Missing aspects must be required: {sorted(unknown)}")
        return self


class RetrievalStep(BaseModel):
    document_ids: list[str] = Field(default_factory=list)
    error_type: str | None = None

    @model_validator(mode="after")
    def error_step_has_no_documents(self) -> "RetrievalStep":
        if self.error_type not in {None, "TimeoutError"}:
            raise ValueError("Only the allowlisted TimeoutError may be injected")
        if self.error_type and self.document_ids:
            raise ValueError("A retrieval step cannot contain documents and an error")
        return self


class TrajectoryLabel(BaseModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    query: str = Field(min_length=2)
    retrieval_steps: list[RetrievalStep] = Field(min_length=1, max_length=2)
    oracle_sufficient_after_step: list[bool] = Field(min_length=1, max_length=2)
    split: DatasetSplit
    rationale: str = Field(min_length=1)
    annotator: str = Field(min_length=1)
    reviewed: bool = False

    @model_validator(mode="after")
    def oracle_matches_steps(self) -> "TrajectoryLabel":
        if len(self.retrieval_steps) != len(self.oracle_sufficient_after_step):
            raise ValueError("Every retrieval step needs an oracle sufficiency label")
        return self
