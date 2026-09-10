from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class ContextBudgetError(RuntimeError):
    """Mandatory context cannot fit without violating the output reserve."""


class ContextKind(StrEnum):
    SYSTEM = "system"
    USER_REQUEST = "user_request"
    CONSTRAINTS = "constraints"
    EVIDENCE = "evidence"
    HISTORY = "history"


class ContextItem(BaseModel):
    item_id: str = Field(min_length=1)
    kind: ContextKind
    content: str = Field(min_length=1)
    priority: int = Field(default=50, ge=0, le=100)
    mandatory: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)


class ContextBudget(BaseModel):
    max_context_tokens: int = Field(ge=64)
    reserved_output_tokens: int = Field(ge=1)
    safety_margin_tokens: int = Field(default=0, ge=0)
    max_tokens_per_evidence: int = Field(default=256, ge=16)
    min_tokens_for_clipped_evidence: int = Field(default=24, ge=8)

    @model_validator(mode="after")
    def reserves_leave_input_capacity(self) -> ContextBudget:
        if self.reserved_output_tokens + self.safety_margin_tokens >= self.max_context_tokens:
            raise ValueError("Output reserve and safety margin leave no input capacity")
        if self.min_tokens_for_clipped_evidence > self.max_tokens_per_evidence:
            raise ValueError("Minimum clipped evidence size exceeds per-evidence maximum")
        return self

    @property
    def input_token_limit(self) -> int:
        return self.max_context_tokens - self.reserved_output_tokens - self.safety_margin_tokens


class ContextItemTrace(BaseModel):
    item_id: str
    kind: ContextKind
    estimated_tokens_before: int = Field(ge=0)
    estimated_tokens_after: int = Field(ge=0)
    action: str
    reason_code: str


class ContextTrace(BaseModel):
    trace_version: str = "context-trace-v1"
    mode: str
    estimator: str
    max_context_tokens: int | None = None
    input_token_limit: int | None = None
    reserved_output_tokens: int = 0
    safety_margin_tokens: int = 0
    estimated_input_tokens_before: int = Field(ge=0)
    estimated_input_tokens_after: int = Field(ge=0)
    included_item_ids: list[str] = Field(default_factory=list)
    clipped_item_ids: list[str] = Field(default_factory=list)
    dropped_item_ids: list[str] = Field(default_factory=list)
    coverage_targets: list[str] = Field(default_factory=list)
    items: list[ContextItemTrace] = Field(default_factory=list)
    degraded_components: list[str] = Field(default_factory=list)


class PackedContext(BaseModel):
    rendered: str
    items: list[ContextItem]
    trace: ContextTrace


class DuplicateGroupTrace(BaseModel):
    kept_item_id: str
    suppressed_item_ids: list[str]


class ConflictTrace(BaseModel):
    fact_key: str
    status: str
    kept_item_ids: list[str]
    suppressed_item_ids: list[str] = Field(default_factory=list)
    reason_code: str


class EvidenceRefinementTrace(BaseModel):
    trace_version: str = "evidence-refinement-v1"
    duplicate_groups: list[DuplicateGroupTrace] = Field(default_factory=list)
    conflicts: list[ConflictTrace] = Field(default_factory=list)
    compressed_item_ids: list[str] = Field(default_factory=list)
    compression_skipped_item_ids: list[str] = Field(default_factory=list)
    estimated_evidence_tokens_before: int = Field(ge=0)
    estimated_evidence_tokens_after: int = Field(ge=0)
    degraded_components: list[str] = Field(default_factory=list)


class RefinedContextItems(BaseModel):
    items: list[ContextItem]
    trace: EvidenceRefinementTrace


class RefinedPackedContext(BaseModel):
    packed: PackedContext
    refinement_trace: EvidenceRefinementTrace
