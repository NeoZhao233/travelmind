from __future__ import annotations

import hashlib
import math
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from travelmind.domain.models import RetrievalExample
from travelmind.evaluation.metrics import evaluate_rankings
from travelmind.ingestion.dataset import load_jsonl, validate_seed_dataset
from travelmind.retrieval.bm25 import BM25Retriever
from travelmind.retrieval.embeddings import BGE_SMALL_ZH_V15, FastEmbedProvider
from travelmind.retrieval.models import SearchResponse
from travelmind.retrieval.reranking import BGE_RERANKER_BASE

_DATASET_PATHS = (
    "data/seed/places.jsonl",
    "data/seed/documents.jsonl",
    "data/seed/facts.jsonl",
    "evals/datasets/retrieval_seed.jsonl",
)


def _dataset_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for relative_path in _DATASET_PATHS:
        digest.update(relative_path.encode())
        digest.update(b"\0")
        digest.update((root / relative_path).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


class _Ranker(Protocol):
    def rank(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> SearchResponse: ...


def _evaluate_ranker(
    *,
    root: Path,
    examples: list[RetrievalExample],
    summary: Any,
    ranker: _Ranker,
    experiment: str,
    configuration: dict[str, Any],
    limitations: list[str],
    limit: int,
    apply_filters: bool,
    build_latency_ms: float,
) -> dict[str, Any]:
    rankings: dict[str, list[str]] = {}
    scores: dict[str, list[dict[str, float | str]]] = {}
    query_diagnostics: dict[str, dict[str, Any]] = {}
    unsupported_filter_counts: Counter[str] = Counter()
    retrieval_mode_counts: Counter[str] = Counter()
    channel_status_counts: Counter[str] = Counter()
    degraded_component_counts: Counter[str] = Counter()
    fallback_counts: Counter[str] = Counter()
    reranker_status_counts: Counter[str] = Counter()
    degraded_query_count = 0
    latency_ms: list[float] = []
    for example in examples:
        started = perf_counter()
        response = ranker.rank(
            example.query,
            limit=limit,
            filters=example.hard_filters if apply_filters else None,
        )
        latency_ms.append((perf_counter() - started) * 1000)
        rankings[example.query_id] = [hit.document_id for hit in response.hits]
        scores[example.query_id] = [
            {"document_id": hit.document_id, "score": round(hit.score, 8)} for hit in response.hits
        ]
        unsupported_filter_counts.update(response.unsupported_filters)
        if response.diagnostics:
            query_diagnostics[example.query_id] = response.diagnostics
            mode = response.diagnostics.get("retrieval_mode")
            if isinstance(mode, str):
                retrieval_mode_counts[mode] += 1
            for channel, details in response.diagnostics.get("channels", {}).items():
                status = details.get("status") if isinstance(details, dict) else None
                if isinstance(status, str):
                    channel_status_counts[f"{channel}:{status}"] += 1
            degraded_component_counts.update(response.diagnostics.get("degraded_components", []))
            fallback_counts.update(response.diagnostics.get("fallbacks_used", []))
            if response.diagnostics.get("degraded_components"):
                degraded_query_count += 1
            reranker = response.diagnostics.get("reranker")
            if isinstance(reranker, dict) and isinstance(reranker.get("status"), str):
                reranker_status_counts[reranker["status"]] += 1

    metrics = evaluate_rankings(examples, rankings)
    per_query_details = {row["query_id"]: row for row in metrics.pop("per_query")}
    for query_id, detail in per_query_details.items():
        detail["ranked_scores"] = scores[query_id]
        if query_id in query_diagnostics:
            detail["retrieval_diagnostics"] = query_diagnostics[query_id]

    metrics_by_query_type: dict[str, dict[str, Any]] = {}
    for query_type in sorted({example.query_type.value for example in examples}):
        type_examples = [example for example in examples if example.query_type.value == query_type]
        type_metrics = evaluate_rankings(type_examples, rankings)
        type_metrics.pop("per_query")
        metrics_by_query_type[query_type] = type_metrics

    return {
        "schema_version": 1,
        "experiment": experiment,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_fingerprint_sha256": _dataset_fingerprint(root),
        "dataset_summary": summary.model_dump(mode="json"),
        "configuration": configuration,
        "metrics": metrics,
        "metrics_by_query_type": metrics_by_query_type,
        "build_latency_ms": build_latency_ms,
        "latency_ms": {
            "mean": sum(latency_ms) / len(latency_ms),
            "p95": _percentile(latency_ms, 0.95),
            "samples": len(latency_ms),
            "scope": "in-process search only; excludes process startup and index construction",
        },
        "unsupported_filter_counts": dict(sorted(unsupported_filter_counts.items())),
        "retrieval_diagnostics": {
            "retrieval_mode_counts": dict(sorted(retrieval_mode_counts.items())),
            "degraded_query_count": degraded_query_count,
            "channel_status_counts": dict(sorted(channel_status_counts.items())),
            "degraded_component_counts": dict(sorted(degraded_component_counts.items())),
            "fallback_counts": dict(sorted(fallback_counts.items())),
            "reranker_status_counts": dict(sorted(reranker_status_counts.items())),
        },
        "per_query": list(per_query_details.values()),
        "limitations": limitations,
    }


def run_bm25_experiment(
    root: Path,
    *,
    limit: int = 10,
    k1: float = 1.5,
    b: float = 0.75,
    apply_filters: bool = False,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be positive")
    root = root.resolve()
    summary = validate_seed_dataset(root)
    examples = load_jsonl(root / "evals/datasets/retrieval_seed.jsonl", RetrievalExample)
    build_started = perf_counter()
    retriever = BM25Retriever.from_project(root, k1=k1, b=b)
    build_latency_ms = (perf_counter() - build_started) * 1000
    return _evaluate_ranker(
        root=root,
        examples=examples,
        summary=summary,
        ranker=retriever,
        experiment=(
            "bm25-char-unigram-bigram-filtered"
            if apply_filters
            else "bm25-char-unigram-bigram-lexical"
        ),
        configuration={
            "retriever": "in_process_bm25",
            "tokenizer": "nfkc_lowercase_ascii_terms_cjk_unigrams_bigrams",
            "k1": k1,
            "b": b,
            "limit": limit,
            "apply_supported_metadata_filters": apply_filters,
            "metric_cutoffs": [1, 3, 5, 10],
            "ground_truth_level": "source_document_section",
        },
        limitations=[
            "The 15-query seed set is small, single-annotator, and not a held-out benchmark.",
            "Latency on an in-memory 14-document corpus does not predict production latency.",
            "When filters are enabled, unsupported hard-filter keys are reported and left to "
            "lexical matching.",
            "No statistical significance or generalization claim is made.",
        ],
        limit=limit,
        apply_filters=apply_filters,
        build_latency_ms=build_latency_ms,
    )


def run_dense_experiment(
    root: Path,
    *,
    limit: int = 10,
    model_name: str = BGE_SMALL_ZH_V15,
    cache_dir: Path | None = None,
    local_files_only: bool = False,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be positive")
    root = root.resolve()
    summary = validate_seed_dataset(root)
    examples = load_jsonl(root / "evals/datasets/retrieval_seed.jsonl", RetrievalExample)
    build_started = perf_counter()
    embedder = FastEmbedProvider(
        model_name=model_name,
        cache_dir=cache_dir or root / ".cache/fastembed",
        local_files_only=local_files_only,
    )
    from travelmind.retrieval.dense import QdrantDenseRetriever

    retriever = QdrantDenseRetriever.from_project(root, embedder=embedder)
    build_latency_ms = (perf_counter() - build_started) * 1000
    return _evaluate_ranker(
        root=root,
        examples=examples,
        summary=summary,
        ranker=retriever,
        experiment="qdrant-dense-bge-small-zh-v1.5",
        configuration={
            "retriever": "qdrant_local_dense",
            "qdrant_client_version": version("qdrant-client"),
            "distance": "cosine",
            "limit": limit,
            "apply_supported_metadata_filters": False,
            "metric_cutoffs": [1, 3, 5, 10],
            "ground_truth_level": "source_document_section",
            "embedding": embedder.runtime_metadata(),
            "model_cache_mode": "local_only" if local_files_only else "download_if_missing",
        },
        limitations=[
            "The 15-query seed set is small, single-annotator, and not a held-out benchmark.",
            "Qdrant local mode measures retrieval behavior, not remote service latency or HNSW "
            "scale.",
            "The cached artifact is checksummed, but the external registry remains outside project "
            "control until provisioning verifies an expected checksum.",
            "No metadata filters, reranker, or hybrid fusion are applied in this dense baseline.",
            "No statistical significance or generalization claim is made.",
        ],
        limit=limit,
        apply_filters=False,
        build_latency_ms=build_latency_ms,
    )


def run_hybrid_experiment(
    root: Path,
    *,
    limit: int = 10,
    k1: float = 1.5,
    b: float = 0.75,
    model_name: str = BGE_SMALL_ZH_V15,
    cache_dir: Path | None = None,
    local_files_only: bool = False,
    rrf_k: int = 60,
    candidate_limit: int = 10,
    channel_timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be positive")
    if rrf_k < 1:
        raise ValueError("rrf_k must be positive")
    if candidate_limit < 1:
        raise ValueError("candidate_limit must be positive")
    if channel_timeout_seconds <= 0:
        raise ValueError("channel_timeout_seconds must be positive")

    root = root.resolve()
    summary = validate_seed_dataset(root)
    examples = load_jsonl(root / "evals/datasets/retrieval_seed.jsonl", RetrievalExample)
    build_started = perf_counter()
    sparse = BM25Retriever.from_project(root, k1=k1, b=b)
    embedder = FastEmbedProvider(
        model_name=model_name,
        cache_dir=cache_dir or root / ".cache/fastembed",
        local_files_only=local_files_only,
    )
    from travelmind.retrieval.dense import QdrantDenseRetriever
    from travelmind.retrieval.hybrid import HybridRetriever

    dense = QdrantDenseRetriever.from_project(root, embedder=embedder)
    retriever = HybridRetriever(
        sparse=sparse,
        dense=dense,
        rrf_k=rrf_k,
        candidate_limit=candidate_limit,
        channel_timeout_seconds=channel_timeout_seconds,
    )
    build_latency_ms = (perf_counter() - build_started) * 1000
    return _evaluate_ranker(
        root=root,
        examples=examples,
        summary=summary,
        ranker=retriever,
        experiment="hybrid-bm25-bge-small-zh-v1.5-rrf",
        configuration={
            "retriever": "parallel_bm25_qdrant_dense_rrf",
            "execution": "two_thread_concurrent",
            "sparse": {
                "tokenizer": "nfkc_lowercase_ascii_terms_cjk_unigrams_bigrams",
                "k1": k1,
                "b": b,
            },
            "dense": {
                "qdrant_client_version": version("qdrant-client"),
                "distance": "cosine",
                "embedding": embedder.runtime_metadata(),
                "model_cache_mode": ("local_only" if local_files_only else "download_if_missing"),
            },
            "fusion": {
                "algorithm": "reciprocal_rank_fusion",
                "rrf_k": rrf_k,
                "candidate_limit_per_channel": max(limit, candidate_limit),
            },
            "channel_timeout_seconds": channel_timeout_seconds,
            "limit": limit,
            "apply_supported_metadata_filters": False,
            "metric_cutoffs": [1, 3, 5, 10],
            "ground_truth_level": "source_document_section",
        },
        limitations=[
            "The 15-query seed set is small, single-annotator, and not a held-out benchmark.",
            "RRF k=60 and candidate depth are untuned defaults, not optimized on a held-out set.",
            "Qdrant local mode and an in-process embedding model do not represent service latency.",
            "Thread timeouts stop waiting but cannot terminate already-running provider calls; "
            "provider-native timeouts remain required in production.",
            "No metadata filters, query rewrite, or reranker are applied in this hybrid baseline.",
            "No statistical significance or generalization claim is made.",
        ],
        limit=limit,
        apply_filters=False,
        build_latency_ms=build_latency_ms,
    )


def run_reranked_hybrid_experiment(
    root: Path,
    *,
    limit: int = 10,
    k1: float = 1.5,
    b: float = 0.75,
    model_name: str = BGE_SMALL_ZH_V15,
    reranker_model_name: str = BGE_RERANKER_BASE,
    cache_dir: Path | None = None,
    local_files_only: bool = False,
    rrf_k: int = 60,
    hybrid_candidate_limit: int = 10,
    channel_timeout_seconds: float = 5.0,
    rerank_candidate_limit: int = 10,
    reranker_timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be positive")
    if rerank_candidate_limit < limit:
        raise ValueError("rerank_candidate_limit must be at least limit")

    root = root.resolve()
    summary = validate_seed_dataset(root)
    examples = load_jsonl(root / "evals/datasets/retrieval_seed.jsonl", RetrievalExample)
    model_cache = cache_dir or root / ".cache/fastembed"
    build_started = perf_counter()
    sparse = BM25Retriever.from_project(root, k1=k1, b=b)
    embedder = FastEmbedProvider(
        model_name=model_name,
        cache_dir=model_cache,
        local_files_only=local_files_only,
    )
    from travelmind.retrieval.dense import QdrantDenseRetriever
    from travelmind.retrieval.hybrid import HybridRetriever
    from travelmind.retrieval.reranking import (
        FastEmbedCrossEncoderProvider,
        RerankingRetriever,
    )

    dense = QdrantDenseRetriever.from_project(root, embedder=embedder)
    hybrid = HybridRetriever(
        sparse=sparse,
        dense=dense,
        rrf_k=rrf_k,
        candidate_limit=max(hybrid_candidate_limit, rerank_candidate_limit),
        channel_timeout_seconds=channel_timeout_seconds,
    )
    reranker = FastEmbedCrossEncoderProvider(
        model_name=reranker_model_name,
        cache_dir=model_cache,
        local_files_only=local_files_only,
    )
    retriever = RerankingRetriever(
        base=hybrid,
        reranker=reranker,
        candidate_limit=rerank_candidate_limit,
        timeout_seconds=reranker_timeout_seconds,
    )
    build_latency_ms = (perf_counter() - build_started) * 1000
    return _evaluate_ranker(
        root=root,
        examples=examples,
        summary=summary,
        ranker=retriever,
        experiment="hybrid-rrf-bge-reranker-base",
        configuration={
            "retriever": "parallel_bm25_qdrant_dense_rrf_cross_encoder",
            "sparse": {"k1": k1, "b": b},
            "dense": {
                "qdrant_client_version": version("qdrant-client"),
                "distance": "cosine",
                "embedding": embedder.runtime_metadata(),
            },
            "fusion": {
                "algorithm": "reciprocal_rank_fusion",
                "rrf_k": rrf_k,
                "candidate_limit_per_channel": max(
                    limit, hybrid_candidate_limit, rerank_candidate_limit
                ),
            },
            "reranker": {
                **reranker.runtime_metadata(),
                "candidate_limit": rerank_candidate_limit,
                "timeout_seconds": reranker_timeout_seconds,
                "fallback": "preserve_rrf_order",
            },
            "channel_timeout_seconds": channel_timeout_seconds,
            "model_cache_mode": "local_only" if local_files_only else "download_if_missing",
            "limit": limit,
            "apply_supported_metadata_filters": False,
            "metric_cutoffs": [1, 3, 5, 10],
            "ground_truth_level": "source_document_section",
        },
        limitations=[
            "The 15-query seed set is small, single-annotator, and not a held-out benchmark.",
            "The reranker sees only ten retrieved candidates and cannot recover omitted evidence.",
            "The 1.04GB registered model size and local CPU latency may not justify small gains.",
            "Thread deadlines stop waiting but cannot terminate already-running inference.",
            "Qdrant local mode and in-process ONNX do not represent production p95 latency.",
            "No metadata filters or query rewrite are applied.",
            "No statistical significance or generalization claim is made.",
        ],
        limit=limit,
        apply_filters=False,
        build_latency_ms=build_latency_ms,
    )
