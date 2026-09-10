from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Any

import pytest

from travelmind.retrieval.hybrid import HybridRetrievalError, HybridRetriever
from travelmind.retrieval.models import RetrievalHit, SearchResponse


def _hit(document_id: str, score: float) -> RetrievalHit:
    return RetrievalHit(
        document_id=document_id,
        chunk_id=f"{document_id}-chunk",
        score=score,
        content=f"content for {document_id}",
        source_url=f"https://example.com/{document_id}",
        metadata={"place_id": document_id},
    )


@dataclass
class StaticRanker:
    document_ids: list[str]

    def rank(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> SearchResponse:
        del query, filters
        hits = tuple(
            _hit(document_id, 10.0 - rank)
            for rank, document_id in enumerate(self.document_ids[:limit])
        )
        return SearchResponse(hits=hits, candidate_documents=len(hits))


class FailingRanker:
    def rank(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> SearchResponse:
        del query, limit, filters
        raise RuntimeError("provider unavailable secret=must-not-appear-beyond-truncation")


class SlowRanker:
    def rank(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> SearchResponse:
        del query, limit, filters
        sleep(0.03)
        return SearchResponse(hits=(_hit("late", 1.0),))


def test_hybrid_rrf_rewards_documents_found_by_both_channels() -> None:
    retriever = HybridRetriever(
        sparse=StaticRanker(["a", "b", "c"]),
        dense=StaticRanker(["b", "d", "a"]),
    )

    response = retriever.rank("query", limit=4)

    assert [hit.document_id for hit in response.hits][:2] == ["b", "a"]
    assert response.diagnostics["retrieval_mode"] == "hybrid"
    assert response.diagnostics["degraded_components"] == []
    assert response.hits[0].metadata["channel_details"]["sparse"]["rank"] == 2
    assert response.hits[0].metadata["channel_details"]["dense"]["rank"] == 1


def test_hybrid_falls_back_to_surviving_channel_and_records_reason() -> None:
    retriever = HybridRetriever(
        sparse=StaticRanker(["a", "b"]),
        dense=FailingRanker(),
    )

    response = retriever.rank("query")

    assert [hit.document_id for hit in response.hits] == ["a", "b"]
    assert response.diagnostics["retrieval_mode"] == "sparse_only"
    assert response.diagnostics["degraded_components"] == ["dense"]
    assert response.diagnostics["fallbacks_used"] == ["use_sparse_only"]
    assert response.diagnostics["channels"]["dense"]["status"] == "error"
    assert response.diagnostics["channels"]["dense"]["error_type"] == "RuntimeError"
    assert "secret" not in str(response.diagnostics)


def test_hybrid_raises_when_both_channels_fail() -> None:
    retriever = HybridRetriever(sparse=FailingRanker(), dense=FailingRanker())

    with pytest.raises(HybridRetrievalError, match="sparse=error, dense=error"):
        retriever.rank("query")


def test_hybrid_timeout_does_not_discard_healthy_channel() -> None:
    retriever = HybridRetriever(
        sparse=StaticRanker(["a"]),
        dense=SlowRanker(),
        channel_timeout_seconds=0.005,
    )

    response = retriever.rank("query")

    assert [hit.document_id for hit in response.hits] == ["a"]
    assert response.diagnostics["channels"]["dense"]["status"] == "timeout"
    assert response.diagnostics["retrieval_mode"] == "sparse_only"


def test_hybrid_accepts_successful_empty_responses() -> None:
    retriever = HybridRetriever(
        sparse=StaticRanker([]),
        dense=StaticRanker([]),
    )

    response = retriever.rank("query")

    assert response.hits == ()
    assert response.diagnostics["retrieval_mode"] == "hybrid"


def test_hybrid_graph_adapter_marks_rrf_scores() -> None:
    retriever = HybridRetriever(
        sparse=StaticRanker(["a"]),
        dense=StaticRanker(["a"]),
    )

    evidence = retriever.search(["first", "second"], limit=1)

    assert evidence[0].metadata["score_type"] == "rrf"
    assert evidence[0].metadata["retrieval_mode"] == "hybrid"


def test_hybrid_rejects_filters_until_both_channels_share_semantics() -> None:
    retriever = HybridRetriever(sparse=StaticRanker([]), dense=StaticRanker([]))

    with pytest.raises(ValueError, match="does not support metadata filters"):
        retriever.rank("query", filters={"city": "北京"})
