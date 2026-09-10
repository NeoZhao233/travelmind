from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from travelmind.retrieval.models import RetrievalHit, SearchResponse
from travelmind.retrieval.multi_query import MultiQueryRetrievalError, MultiQueryRRFAdapter


def _hit(document_id: str, score: float) -> RetrievalHit:
    return RetrievalHit(
        document_id=document_id,
        chunk_id=f"{document_id}-chunk",
        score=score,
        content=document_id,
        source_url=f"https://example.com/{document_id}",
        metadata={},
    )


@dataclass
class QueryRanker:
    rankings: dict[str, list[str]]
    failures: set[str]

    def rank(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> SearchResponse:
        del filters
        if query in self.failures:
            raise RuntimeError("provider details must not propagate")
        return SearchResponse(
            hits=tuple(
                _hit(document_id, 10 - rank)
                for rank, document_id in enumerate(self.rankings.get(query, [])[:limit])
            )
        )


def test_multi_query_executes_variants_independently_and_fuses_ranks() -> None:
    adapter = MultiQueryRRFAdapter(
        ranker=QueryRanker(
            rankings={"original": ["a", "b"], "rewrite": ["b", "c"]},
            failures=set(),
        )
    )

    evidence = adapter.search(["original", "rewrite"], limit=3)

    assert [item.metadata["document_id"] for item in evidence] == ["b", "a", "c"]
    assert evidence[0].metadata["executed_query_count"] == 2
    assert evidence[0].metadata["contributing_query_indexes"] == [0, 1]


def test_multi_query_survives_one_query_failure_and_marks_degradation() -> None:
    adapter = MultiQueryRRFAdapter(
        ranker=QueryRanker(rankings={"healthy": ["a"]}, failures={"broken"})
    )

    evidence = adapter.search(["broken", "healthy"], limit=1)

    assert evidence[0].metadata["document_id"] == "a"
    assert evidence[0].metadata["failed_query_count"] == 1
    assert "provider details" not in str(evidence)


def test_multi_query_raises_only_when_every_query_fails() -> None:
    adapter = MultiQueryRRFAdapter(ranker=QueryRanker(rankings={}, failures={"one", "two"}))

    with pytest.raises(MultiQueryRetrievalError, match="RuntimeError"):
        adapter.search(["one", "two"], limit=3)


def test_multi_query_deduplicates_and_bounds_query_fanout() -> None:
    adapter = MultiQueryRRFAdapter(
        ranker=QueryRanker(
            rankings={"one": ["a"], "two": ["b"], "three": ["c"]},
            failures=set(),
        ),
        max_queries=2,
    )

    evidence = adapter.search(["one", "one", "two", "three"], limit=2)

    assert {item.metadata["document_id"] for item in evidence} == {"a", "b"}
    assert evidence[0].metadata["executed_query_count"] == 2
    assert evidence[0].metadata["truncated_query_count"] == 1
