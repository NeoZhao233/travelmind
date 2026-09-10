from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RetrievalHit:
    document_id: str
    chunk_id: str
    score: float
    content: str
    source_url: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SearchResponse:
    hits: tuple[RetrievalHit, ...]
    unsupported_filters: tuple[str, ...] = ()
    candidate_documents: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)
