"""Travel-domain records shared by ingestion, retrieval, and evaluation."""

from travelmind.domain.models import (
    Chunk,
    FactRecord,
    PlaceRecord,
    RetrievalExample,
    SourceDocument,
)

__all__ = [
    "Chunk",
    "FactRecord",
    "PlaceRecord",
    "RetrievalExample",
    "SourceDocument",
]
