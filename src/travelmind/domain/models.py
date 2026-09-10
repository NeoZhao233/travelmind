from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator


class SourceAuthority(StrEnum):
    OFFICIAL_OPERATOR = "official_operator"
    GOVERNMENT = "government"
    OFFICIAL_AGGREGATOR = "official_aggregator"
    THIRD_PARTY = "third_party"


class FreshnessClass(StrEnum):
    STATIC = "static"
    SEASONAL = "seasonal"
    DYNAMIC = "dynamic"


class FactType(StrEnum):
    DESCRIPTION = "description"
    OPENING_HOURS = "opening_hours"
    ADMISSION = "admission"
    BOOKING = "booking"
    ACCESS = "access"
    TRANSPORT = "transport"
    ACCESSIBILITY = "accessibility"


class QueryType(StrEnum):
    SEMANTIC = "semantic"
    EXACT = "exact"
    METADATA = "metadata"
    TEMPORAL = "temporal"
    MULTI_CONSTRAINT = "multi_constraint"


class PlaceRecord(BaseModel):
    place_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    name: str = Field(min_length=1)
    city: str = Field(min_length=1)
    district: str | None = None
    categories: list[str] = Field(min_length=1)
    official_url: AnyHttpUrl
    longitude: float | None = Field(default=None, ge=-180, le=180)
    latitude: float | None = Field(default=None, ge=-90, le=90)

    @model_validator(mode="after")
    def coordinates_are_both_present_or_absent(self) -> PlaceRecord:
        if (self.longitude is None) != (self.latitude is None):
            raise ValueError("longitude and latitude must be provided together")
        return self


class SourceDocument(BaseModel):
    document_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    place_id: str
    title: str = Field(min_length=1)
    section: str = Field(min_length=1)
    content: str = Field(min_length=20)
    source_url: AnyHttpUrl
    authority: SourceAuthority
    freshness: FreshnessClass
    language: str = "zh-CN"
    source_updated_at: date | None = None
    collected_at: datetime
    valid_from: date | None = None
    valid_to: date | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("collected_at")
    @classmethod
    def collected_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validity_range_is_ordered(self) -> SourceDocument:
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not be earlier than valid_from")
        return self


class FactRecord(BaseModel):
    fact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    place_id: str
    document_id: str
    fact_type: FactType
    value: str | int | float | bool
    unit: str | None = None
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime
    valid_from: date | None = None
    valid_to: date | None = None

    @field_validator("observed_at")
    @classmethod
    def observed_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validity_range_is_ordered(self) -> FactRecord:
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not be earlier than valid_from")
        return self


class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    place_id: str
    ordinal: int = Field(ge=0)
    content: str = Field(min_length=1)
    char_count: int = Field(gt=0)
    token_estimate: int = Field(gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalExample(BaseModel):
    query_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    query: str = Field(min_length=2)
    query_type: QueryType
    relevant_documents: dict[str, int] = Field(default_factory=dict)
    expected_place_ids: list[str] = Field(default_factory=list)
    hard_filters: dict[str, Any] = Field(default_factory=dict)
    expected_fact_types: list[FactType] = Field(default_factory=list)
    should_abstain: bool = False
    notes: str = ""
    annotator: str = Field(min_length=1)
    reviewed: bool = False

    @field_validator("relevant_documents")
    @classmethod
    def relevance_grades_are_supported(cls, value: dict[str, int]) -> dict[str, int]:
        invalid = {
            document_id: grade for document_id, grade in value.items() if grade not in {1, 2, 3}
        }
        if invalid:
            raise ValueError(f"relevance grades must be 1, 2, or 3: {invalid}")
        return value

    @model_validator(mode="after")
    def abstention_and_relevance_are_consistent(self) -> RetrievalExample:
        if self.should_abstain and self.relevant_documents:
            raise ValueError("abstention examples must not contain relevant documents")
        if not self.should_abstain and not self.relevant_documents:
            raise ValueError("non-abstention examples require relevant documents")
        return self


class DatasetSummary(BaseModel):
    places: int
    documents: int
    facts: int
    chunks: int
    retrieval_examples: int
    reviewed_examples: int
    query_types: dict[str, int]
