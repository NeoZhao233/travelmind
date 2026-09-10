from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Any

import pytest

from travelmind.retrieval.models import RetrievalHit, SearchResponse
from travelmind.retrieval.reranking import (
    RerankerInferenceError,
    RerankingRetriever,
    validate_scores,
)


def _hit(document_id: str, score: float) -> RetrievalHit:
    return RetrievalHit(
        document_id=document_id,
        chunk_id=f"{document_id}-chunk",
        score=score,
        content=document_id,
        source_url=f"https://example.com/{document_id}",
        metadata={},
    )


class BaseRanker:
    def rank(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> SearchResponse:
        del query, filters
        return SearchResponse(
            hits=tuple(_hit(name, 1 / rank) for rank, name in enumerate("abc", start=1))[:limit],
            candidate_documents=3,
            diagnostics={
                "retrieval_mode": "hybrid",
                "degraded_components": [],
                "fallbacks_used": [],
            },
        )


class EmptyBaseRanker(BaseRanker):
    def rank(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> SearchResponse:
        del query, limit, filters
        return SearchResponse(hits=(), diagnostics={"retrieval_mode": "hybrid"})


@dataclass
class StaticReranker:
    scores: list[float]
    model_name: str = "fake-reranker"

    def score(self, query: str, documents: list[str]) -> list[float]:
        del query, documents
        return self.scores

    def runtime_metadata(self) -> dict[str, Any]:
        return {"model_name": self.model_name}


class FailingReranker(StaticReranker):
    def score(self, query: str, documents: list[str]) -> list[float]:
        del query, documents
        raise RuntimeError("secret=do-not-log")


class SlowReranker(StaticReranker):
    def score(self, query: str, documents: list[str]) -> list[float]:
        del query, documents
        sleep(0.03)
        return self.scores


def test_reranker_changes_order_and_preserves_pre_rerank_details() -> None:
    retriever = RerankingRetriever(
        base=BaseRanker(),
        reranker=StaticReranker([0.1, 0.9, 0.2]),
    )

    response = retriever.rank("query")

    assert [hit.document_id for hit in response.hits] == ["b", "c", "a"]
    assert response.hits[0].metadata["pre_rerank_rank"] == 2
    assert response.hits[0].metadata["reranker_score"] == 0.9
    assert response.diagnostics["retrieval_mode"] == "hybrid_reranked"
    assert response.diagnostics["reranker"]["status"] == "success"


def test_reranker_error_preserves_base_order_and_redacts_message() -> None:
    retriever = RerankingRetriever(
        base=BaseRanker(),
        reranker=FailingReranker([]),
    )

    response = retriever.rank("query")

    assert [hit.document_id for hit in response.hits] == ["a", "b", "c"]
    assert response.diagnostics["reranker"]["status"] == "error"
    assert response.diagnostics["reranker"]["error_type"] == "RuntimeError"
    assert response.diagnostics["fallbacks_used"] == ["preserve_base_order"]
    assert "secret" not in str(response.diagnostics)


def test_reranker_timeout_preserves_base_order() -> None:
    retriever = RerankingRetriever(
        base=BaseRanker(),
        reranker=SlowReranker([0.1, 0.9, 0.2]),
        timeout_seconds=0.005,
    )

    response = retriever.rank("query")

    assert [hit.document_id for hit in response.hits] == ["a", "b", "c"]
    assert response.diagnostics["reranker"]["status"] == "timeout"
    assert response.diagnostics["degraded_components"] == ["reranker"]


@pytest.mark.parametrize("scores", [[0.1], [0.1, float("nan")]])
def test_invalid_reranker_scores_fail_validation(scores: list[float]) -> None:
    with pytest.raises(RerankerInferenceError):
        validate_scores(scores, expected=2)


def test_invalid_scores_from_provider_trigger_base_order_fallback() -> None:
    retriever = RerankingRetriever(
        base=BaseRanker(),
        reranker=StaticReranker([float("inf"), 0.2, 0.1]),
    )

    response = retriever.rank("query")

    assert [hit.document_id for hit in response.hits] == ["a", "b", "c"]
    assert response.diagnostics["reranker"]["error_type"] == "RerankerInferenceError"


def test_graph_adapter_marks_cross_encoder_score() -> None:
    retriever = RerankingRetriever(
        base=BaseRanker(),
        reranker=StaticReranker([0.1, 0.9, 0.2]),
    )

    evidence = retriever.search(["query"], limit=2)

    assert evidence[0].metadata["score_type"] == "cross_encoder"


def test_empty_candidates_skip_reranker() -> None:
    retriever = RerankingRetriever(
        base=EmptyBaseRanker(),
        reranker=StaticReranker([]),
    )

    response = retriever.rank("query")

    assert response.hits == ()
    assert response.diagnostics["reranker"]["status"] == "skipped_empty"
