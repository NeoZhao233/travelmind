from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from travelmind.retrieval.fusion import reciprocal_rank_fusion
from travelmind.retrieval.models import RetrievalHit, SearchResponse
from travelmind.schemas import Evidence


class MultiQueryRetrievalError(RuntimeError):
    """Raised when every independently executed query fails."""


class Ranker(Protocol):
    def rank(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> SearchResponse: ...


class MultiQueryRRFAdapter:
    """Execute bounded query variants independently and fuse their document ranks."""

    def __init__(
        self,
        *,
        ranker: Ranker,
        candidate_limit: int = 10,
        max_queries: int = 4,
        rrf_k: int = 60,
    ) -> None:
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be positive")
        if max_queries < 1:
            raise ValueError("max_queries must be positive")
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        self._ranker = ranker
        self._candidate_limit = candidate_limit
        self._max_queries = max_queries
        self._rrf_k = rrf_k

    def search(self, queries: list[str], *, limit: int) -> list[Evidence]:
        if limit < 1:
            raise ValueError("limit must be positive")
        unique_queries = list(dict.fromkeys(query.strip() for query in queries if query.strip()))
        selected_queries = unique_queries[: self._max_queries]
        if not selected_queries:
            return []

        responses: list[SearchResponse] = []
        failed_query_count = 0
        error_types: list[str] = []
        for query in selected_queries:
            try:
                responses.append(
                    self._ranker.rank(
                        query,
                        limit=max(limit, self._candidate_limit),
                    )
                )
            except Exception as exc:
                failed_query_count += 1
                error_types.append(type(exc).__name__)

        if not responses:
            errors = ",".join(sorted(set(error_types))) or "unknown"
            raise MultiQueryRetrievalError(
                f"Every multi-query retrieval failed; error_types={errors}"
            )

        rankings = [[hit.document_id for hit in response.hits] for response in responses]
        fused = reciprocal_rank_fusion(rankings, k=self._rrf_k)
        hits_by_document: dict[str, RetrievalHit] = {}
        contributing_queries: dict[str, list[int]] = {}
        for query_index, response in enumerate(responses):
            for hit in response.hits:
                hits_by_document.setdefault(hit.document_id, hit)
                contributing_queries.setdefault(hit.document_id, []).append(query_index)

        return [
            Evidence(
                id=hits_by_document[document_id].chunk_id,
                content=hits_by_document[document_id].content,
                source_url=hits_by_document[document_id].source_url,
                source_type="official",
                score=score,
                retrieved_at=datetime.now(UTC),
                metadata={
                    "document_id": document_id,
                    "score_type": "multi_query_rrf",
                    "executed_query_count": len(selected_queries),
                    "truncated_query_count": len(unique_queries) - len(selected_queries),
                    "failed_query_count": failed_query_count,
                    "contributing_query_indexes": contributing_queries[document_id],
                    **hits_by_document[document_id].metadata,
                },
            )
            for document_id, score in fused[:limit]
        ]
