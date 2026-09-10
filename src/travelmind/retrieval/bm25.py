from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from travelmind.domain.models import Chunk, FactRecord, FactType, PlaceRecord, SourceDocument
from travelmind.ingestion.chunking import chunk_documents
from travelmind.ingestion.dataset import load_jsonl, validate_seed_dataset
from travelmind.retrieval.corpus import build_searchable_text
from travelmind.retrieval.models import RetrievalHit, SearchResponse
from travelmind.retrieval.tokenization import tokenize_for_lexical_search
from travelmind.schemas import Evidence

SUPPORTED_FILTERS = frozenset(
    {
        "city",
        "district",
        "category",
        "admission_max_cny",
        "booking_required",
        "accessibility",
    }
)


class BM25Retriever:
    """In-process BM25 baseline with deterministic Chinese character n-gram tokenization."""

    def __init__(
        self,
        *,
        places: list[PlaceRecord],
        documents: list[SourceDocument],
        facts: list[FactRecord],
        chunks: list[Chunk],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        if not documents or not chunks:
            raise ValueError("BM25 requires at least one document and chunk")
        if k1 <= 0:
            raise ValueError("k1 must be positive")
        if not 0 <= b <= 1:
            raise ValueError("b must be between 0 and 1")

        self.k1 = k1
        self.b = b
        self._place_by_id = {place.place_id: place for place in places}
        self._document_by_id = {document.document_id: document for document in documents}
        self._facts_by_place: dict[str, list[FactRecord]] = {}
        for fact in facts:
            self._facts_by_place.setdefault(fact.place_id, []).append(fact)
        self._chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}

        self._tokens_by_chunk: dict[str, list[str]] = {}
        self._term_frequencies: dict[str, Counter[str]] = {}
        document_frequency: Counter[str] = Counter()
        for chunk in chunks:
            source = self._document_by_id[chunk.document_id]
            place = self._place_by_id[chunk.place_id]
            searchable_text = build_searchable_text(place, source, chunk)
            tokens = tokenize_for_lexical_search(searchable_text)
            self._tokens_by_chunk[chunk.chunk_id] = tokens
            frequencies = Counter(tokens)
            self._term_frequencies[chunk.chunk_id] = frequencies
            document_frequency.update(frequencies.keys())

        self._average_length = sum(map(len, self._tokens_by_chunk.values())) / len(chunks)
        chunk_count = len(chunks)
        self._idf = {
            term: math.log(1 + (chunk_count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    @classmethod
    def from_project(cls, root: Path, *, k1: float = 1.5, b: float = 0.75) -> BM25Retriever:
        root = root.resolve()
        validate_seed_dataset(root)
        places = load_jsonl(root / "data/seed/places.jsonl", PlaceRecord)
        documents = load_jsonl(root / "data/seed/documents.jsonl", SourceDocument)
        facts = load_jsonl(root / "data/seed/facts.jsonl", FactRecord)
        return cls(
            places=places,
            documents=documents,
            facts=facts,
            chunks=chunk_documents(documents),
            k1=k1,
            b=b,
        )

    def _score_chunk(self, chunk_id: str, query_terms: set[str]) -> float:
        frequencies = self._term_frequencies[chunk_id]
        length = len(self._tokens_by_chunk[chunk_id])
        normalization = self.k1 * (1 - self.b + self.b * length / self._average_length)
        score = 0.0
        for term in query_terms:
            term_frequency = frequencies.get(term, 0)
            if term_frequency == 0:
                continue
            score += self._idf.get(term, 0.0) * (
                term_frequency * (self.k1 + 1) / (term_frequency + normalization)
            )
        return score

    def _booking_required(self, place_id: str) -> bool | None:
        values: set[bool] = set()
        for fact in self._facts_by_place.get(place_id, []):
            if fact.fact_type == FactType.BOOKING:
                values.add(fact.value if isinstance(fact.value, bool) else True)
            qualifier = fact.qualifiers.get("booking_required")
            if isinstance(qualifier, bool):
                values.add(qualifier)
        return values.pop() if len(values) == 1 else None

    def _matches_supported_filters(self, document: SourceDocument, filters: dict[str, Any]) -> bool:
        place = self._place_by_id[document.place_id]
        if "city" in filters and place.city != filters["city"]:
            return False
        if "district" in filters and place.district != filters["district"]:
            return False
        if "category" in filters and filters["category"] not in place.categories:
            return False

        facts = self._facts_by_place.get(place.place_id, [])
        if "admission_max_cny" in filters:
            prices = [
                float(fact.value)
                for fact in facts
                if fact.fact_type == FactType.ADMISSION
                and isinstance(fact.value, (int, float))
                and not isinstance(fact.value, bool)
                and fact.unit == "CNY"
            ]
            if not prices or min(prices) > float(filters["admission_max_cny"]):
                return False
        if "booking_required" in filters:
            if self._booking_required(place.place_id) is not filters["booking_required"]:
                return False
        if "accessibility" in filters:
            has_accessibility = any(fact.fact_type == FactType.ACCESSIBILITY for fact in facts)
            if has_accessibility is not filters["accessibility"]:
                return False
        return True

    @staticmethod
    def _validate_supported_filter_values(filters: dict[str, Any]) -> None:
        for key in ("city", "district", "category"):
            if key in filters and not isinstance(filters[key], str):
                raise ValueError(f"{key} filter must be a string")
        if "admission_max_cny" in filters:
            value = filters["admission_max_cny"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError("admission_max_cny filter must be a non-negative number")
        for key in ("booking_required", "accessibility"):
            if key in filters and not isinstance(filters[key], bool):
                raise ValueError(f"{key} filter must be a boolean")

    def rank(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> SearchResponse:
        if limit < 1:
            raise ValueError("limit must be positive")
        filters = filters or {}
        unsupported = tuple(sorted(set(filters) - SUPPORTED_FILTERS))
        supported = {key: value for key, value in filters.items() if key in SUPPORTED_FILTERS}
        self._validate_supported_filter_values(supported)
        query_terms = set(tokenize_for_lexical_search(query))
        if not query_terms:
            return SearchResponse((), unsupported, 0)

        best_by_document: dict[str, tuple[float, Chunk]] = {}
        candidate_documents: set[str] = set()
        for chunk_id, chunk in self._chunk_by_id.items():
            document = self._document_by_id[chunk.document_id]
            if not self._matches_supported_filters(document, supported):
                continue
            candidate_documents.add(document.document_id)
            score = self._score_chunk(chunk_id, query_terms)
            if score <= 0:
                continue
            previous = best_by_document.get(document.document_id)
            if previous is None or score > previous[0]:
                best_by_document[document.document_id] = (score, chunk)

        ordered = sorted(
            best_by_document.items(),
            key=lambda item: (-item[1][0], item[0]),
        )[:limit]
        hits = []
        for document_id, (score, chunk) in ordered:
            document = self._document_by_id[document_id]
            place = self._place_by_id[document.place_id]
            hits.append(
                RetrievalHit(
                    document_id=document_id,
                    chunk_id=chunk.chunk_id,
                    score=score,
                    content=chunk.content,
                    source_url=str(document.source_url),
                    metadata={
                        "place_id": place.place_id,
                        "place_name": place.name,
                        "source_title": document.title,
                        "source_section": document.section,
                        "tags": list(document.tags),
                        "authority": document.authority.value,
                        "freshness": document.freshness.value,
                    },
                )
            )
        return SearchResponse(tuple(hits), unsupported, len(candidate_documents))

    def search(self, queries: list[str], *, limit: int) -> list[Evidence]:
        """Adapt BM25 to the graph's existing Retriever protocol."""

        query = " ".join(part for part in queries if part.strip())
        response = self.rank(query, limit=limit)
        return [
            Evidence(
                id=hit.chunk_id,
                content=hit.content,
                source_url=hit.source_url,
                source_type="official",
                score=hit.score,
                retrieved_at=datetime.now(UTC),
                metadata={"document_id": hit.document_id, **hit.metadata},
            )
            for hit in response.hits
        ]
