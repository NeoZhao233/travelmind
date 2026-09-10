from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from travelmind.agentic.builder import build_agentic_travel_graph
from travelmind.agentic.policies import CoverageEvidenceGrader
from travelmind.domain.models import FactRecord, RetrievalExample
from travelmind.ingestion.dataset import load_jsonl, validate_seed_dataset
from travelmind.planner.demo import DemoPlanner
from travelmind.retrieval.bm25 import BM25Retriever
from travelmind.retrieval.embeddings import BGE_SMALL_ZH_V15, FastEmbedProvider
from travelmind.retrieval.models import SearchResponse
from travelmind.retrieval.multi_query import MultiQueryRRFAdapter
from travelmind.schemas import Evidence, TravelRequest


class _CountingRanker:
    def __init__(self, ranker: Any) -> None:
        self.ranker = ranker
        self.calls = 0
        self.latency_ms = 0.0

    def rank(self, query: str, *, limit: int = 10, filters: dict | None = None) -> SearchResponse:
        self.calls += 1
        started = perf_counter()
        try:
            return self.ranker.rank(query, limit=limit, filters=filters)
        finally:
            self.latency_ms += (perf_counter() - started) * 1000


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _document_ids(evidence: list[Evidence]) -> set[str]:
    return {str(item.metadata.get("document_id", "")) for item in evidence}


def _oracle_supported(
    example: RetrievalExample,
    evidence: list[Evidence],
    fact_types_by_document: dict[str, set[str]],
) -> bool:
    retrieved_relevant = _document_ids(evidence) & set(example.relevant_documents)
    if not retrieved_relevant:
        return False
    expected = {item.value for item in example.expected_fact_types}
    if not expected:
        return True
    covered = {
        fact_type
        for document_id in retrieved_relevant
        for fact_type in fact_types_by_document.get(document_id, set())
    }
    return expected <= covered


def _summarize(rows: list[dict[str, Any]], system: str) -> dict[str, Any]:
    count = len(rows)
    latencies = [row[system]["latency_ms"] for row in rows]
    return {
        "cases": count,
        "supported_completion_rate": sum(
            row[system]["completed"] and row[system]["oracle_supported"] for row in rows
        )
        / count,
        "unsupported_generation_rate": sum(
            row[system]["completed"] and not row[system]["oracle_supported"] for row in rows
        )
        / count,
        "abstention_rate": sum(not row[system]["completed"] for row in rows) / count,
        "average_hybrid_rank_calls": sum(row[system]["rank_calls"] for row in rows) / count,
        "latency_ms": {
            "mean": sum(latencies) / count,
            "p95": _percentile(latencies, 0.95),
        },
    }


def run_live_agentic_experiment(
    root: Path,
    *,
    limit: int = 3,
    local_files_only: bool = True,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be positive")
    root = root.resolve()
    summary = validate_seed_dataset(root)
    examples = load_jsonl(root / "evals/datasets/retrieval_seed.jsonl", RetrievalExample)
    facts = load_jsonl(root / "data/seed/facts.jsonl", FactRecord)
    fact_types_by_document: dict[str, set[str]] = defaultdict(set)
    for fact in facts:
        fact_types_by_document[fact.document_id].add(fact.fact_type.value)

    build_started = perf_counter()
    sparse = BM25Retriever.from_project(root)
    embedder = FastEmbedProvider(
        model_name=BGE_SMALL_ZH_V15,
        cache_dir=root / ".cache/fastembed",
        local_files_only=local_files_only,
    )
    from travelmind.retrieval.dense import QdrantDenseRetriever
    from travelmind.retrieval.hybrid import HybridRetriever

    dense = QdrantDenseRetriever.from_project(root, embedder=embedder)
    hybrid = HybridRetriever(sparse=sparse, dense=dense)
    build_latency_ms = (perf_counter() - build_started) * 1000

    rows = []
    for example in examples:
        request = TravelRequest(query=example.query)

        direct_ranker = _CountingRanker(hybrid)
        direct_retriever = MultiQueryRRFAdapter(ranker=direct_ranker, max_queries=1)
        started = perf_counter()
        direct_evidence = direct_retriever.search([example.query], limit=limit)
        direct_assessment = CoverageEvidenceGrader().grade(request, direct_evidence)
        direct_latency = (perf_counter() - started) * 1000

        agentic_ranker = _CountingRanker(hybrid)
        agentic_retriever = MultiQueryRRFAdapter(ranker=agentic_ranker, max_queries=4)
        graph = build_agentic_travel_graph(
            retriever=agentic_retriever,
            planner=DemoPlanner(),
            retrieval_limit=limit,
            max_retrieval_attempts=2,
        )
        started = perf_counter()
        result = graph.invoke({"request": request})
        agentic_latency = (perf_counter() - started) * 1000
        rows.append(
            {
                "query_id": example.query_id,
                "query_type": example.query_type.value,
                "direct": {
                    "completed": direct_assessment.sufficient,
                    "oracle_supported": _oracle_supported(
                        example, direct_evidence, fact_types_by_document
                    ),
                    "rank_calls": direct_ranker.calls,
                    "latency_ms": direct_latency,
                    "document_ids": sorted(_document_ids(direct_evidence)),
                },
                "agentic": {
                    "completed": result["status"] == "completed",
                    "oracle_supported": _oracle_supported(
                        example, result["evidence"], fact_types_by_document
                    ),
                    "rank_calls": agentic_ranker.calls,
                    "retrieval_attempts": result["retrieval_attempts"],
                    "rewrite_attempts": result["rewrite_attempts"],
                    "latency_ms": agentic_latency,
                    "document_ids": sorted(_document_ids(result["evidence"])),
                    "trajectory": [event.model_dump(mode="json") for event in result["trajectory"]],
                },
            }
        )

    direct_metrics = _summarize(rows, "direct")
    agentic_metrics = _summarize(rows, "agentic")
    digest = hashlib.sha256()
    for relative in (
        "data/seed/documents.jsonl",
        "data/seed/facts.jsonl",
        "evals/datasets/retrieval_seed.jsonl",
    ):
        digest.update((root / relative).read_bytes())
    return {
        "schema_version": 1,
        "experiment": "live-hybrid-direct-vs-agentic-rule-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_fingerprint_sha256": digest.hexdigest(),
        "dataset_summary": summary.model_dump(mode="json"),
        "configuration": {
            "limit": limit,
            "retriever": "BM25 + BGE-small-zh-v1.5 + RRF",
            "agentic_max_attempts": 2,
            "agentic_max_query_fanout": 4,
            "model_cache_mode": "local_only" if local_files_only else "download_if_missing",
        },
        "build_latency_ms": build_latency_ms,
        "direct_metrics": direct_metrics,
        "agentic_metrics": agentic_metrics,
        "rank_call_amplification": (
            agentic_metrics["average_hybrid_rank_calls"]
            / direct_metrics["average_hybrid_rank_calls"]
        ),
        "cases": rows,
        "limitations": [
            "The 15-query seed is small and not an independent held-out Agentic benchmark.",
            "Oracle support uses retrieval relevance plus expected fact-type coverage.",
            "Latency is local in-process execution and excludes model/index construction.",
            "The deterministic planner is not an answer-quality evaluation.",
        ],
    }
