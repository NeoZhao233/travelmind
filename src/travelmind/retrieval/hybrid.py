from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Protocol

from travelmind.retrieval.fusion import reciprocal_rank_fusion
from travelmind.retrieval.models import RetrievalHit, SearchResponse
from travelmind.schemas import Evidence


class HybridRetrievalError(RuntimeError):
    """Raised when neither retrieval channel can produce a response."""


class Ranker(Protocol):
    def rank(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> SearchResponse: ...


class HybridRetriever:
    """Run sparse and dense retrieval concurrently and fuse document ranks with RRF."""

    def __init__(
        self,
        *,
        sparse: Ranker,
        dense: Ranker,
        rrf_k: int = 60,
        candidate_limit: int = 10,
        channel_timeout_seconds: float = 5.0,
    ) -> None:
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be positive")
        if channel_timeout_seconds <= 0:
            raise ValueError("channel_timeout_seconds must be positive")
        self._sparse = sparse
        self._dense = dense
        self._rrf_k = rrf_k
        self._candidate_limit = candidate_limit
        self._channel_timeout_seconds = channel_timeout_seconds

    @staticmethod
    def _run_channel(
        ranker: Ranker,
        query: str,
        limit: int,
    ) -> tuple[SearchResponse | None, BaseException | None, float]:
        started = perf_counter()
        try:
            return ranker.rank(query, limit=limit), None, (perf_counter() - started) * 1000
        except Exception as exc:
            return None, exc, (perf_counter() - started) * 1000

    def rank(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> SearchResponse:
        if limit < 1:
            raise ValueError("limit must be positive")
        if filters:
            raise ValueError(
                "Stage 2C hybrid retrieval does not support metadata filters consistently"
            )

        channel_limit = max(limit, self._candidate_limit)
        rankers = {"sparse": self._sparse, "dense": self._dense}
        executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hybrid-retrieval")
        futures: dict[Future[tuple[SearchResponse | None, BaseException | None, float]], str] = {
            executor.submit(self._run_channel, ranker, query, channel_limit): name
            for name, ranker in rankers.items()
        }
        done, not_done = wait(futures, timeout=self._channel_timeout_seconds)

        responses: dict[str, SearchResponse] = {}
        channels: dict[str, dict[str, Any]] = {}
        for future in done:
            name = futures[future]
            response, error, latency = future.result()
            if error is not None:
                channels[name] = {
                    "status": "error",
                    "latency_ms": latency,
                    # Third-party exception messages can contain credentials or request data.
                    "error_type": type(error).__name__,
                }
            else:
                assert response is not None
                responses[name] = response
                channels[name] = {
                    "status": "success",
                    "latency_ms": latency,
                    "hit_count": len(response.hits),
                }

        for future in not_done:
            name = futures[future]
            future.cancel()
            channels[name] = {
                "status": "timeout",
                "latency_ms": self._channel_timeout_seconds * 1000,
            }

        # Running Python threads cannot be killed. Do not wait for a timed-out channel here;
        # production adapters must also enforce provider-native timeouts.
        executor.shutdown(wait=False, cancel_futures=True)

        channels = {name: channels[name] for name in rankers}
        if not responses:
            states = ", ".join(f"{name}={details['status']}" for name, details in channels.items())
            raise HybridRetrievalError(f"All hybrid retrieval channels failed: {states}")

        successful_names = [name for name in rankers if name in responses]
        retrieval_mode = "hybrid" if len(successful_names) == 2 else f"{successful_names[0]}_only"
        degraded_components = [name for name in rankers if name not in responses]
        rankings = [[hit.document_id for hit in responses[name].hits] for name in successful_names]
        fused = reciprocal_rank_fusion(rankings, k=self._rrf_k)

        hits_by_channel = {
            name: {hit.document_id: hit for hit in response.hits}
            for name, response in responses.items()
        }
        rank_by_channel = {
            name: {hit.document_id: rank for rank, hit in enumerate(response.hits, start=1)}
            for name, response in responses.items()
        }
        fused_hits: list[RetrievalHit] = []
        for document_id, fused_score in fused[:limit]:
            representative = next(
                hits_by_channel[name][document_id]
                for name in successful_names
                if document_id in hits_by_channel[name]
            )
            channel_details = {
                name: {
                    "rank": rank_by_channel[name].get(document_id),
                    "score": (
                        hits_by_channel[name][document_id].score
                        if document_id in hits_by_channel[name]
                        else None
                    ),
                }
                for name in successful_names
            }
            fused_hits.append(
                RetrievalHit(
                    document_id=representative.document_id,
                    chunk_id=representative.chunk_id,
                    score=fused_score,
                    content=representative.content,
                    source_url=representative.source_url,
                    metadata={
                        **representative.metadata,
                        "retrieval_mode": retrieval_mode,
                        "channel_details": channel_details,
                    },
                )
            )

        unsupported = sorted(
            {key for response in responses.values() for key in response.unsupported_filters}
        )
        return SearchResponse(
            hits=tuple(fused_hits),
            unsupported_filters=tuple(unsupported),
            candidate_documents=len(fused),
            diagnostics={
                "retrieval_mode": retrieval_mode,
                "channels": channels,
                "degraded_components": degraded_components,
                "fallbacks_used": (
                    [f"use_{successful_names[0]}_only"] if degraded_components else []
                ),
                "rrf_k": self._rrf_k,
                "candidate_limit_per_channel": channel_limit,
            },
        )

    def search(self, queries: list[str], *, limit: int) -> list[Evidence]:
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
                metadata={
                    "document_id": hit.document_id,
                    "score_type": "rrf",
                    **hit.metadata,
                },
            )
            for hit in response.hits
        ]
