from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

from travelmind.domain.models import RetrievalExample


def _deduplicate(ranking: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(ranking))


def precision_at_k(relevant: set[str], ranking: Sequence[str], k: int) -> float:
    if k < 1:
        raise ValueError("k must be positive")
    top_k = _deduplicate(ranking)[:k]
    return sum(document_id in relevant for document_id in top_k) / k


def recall_at_k(relevant: set[str], ranking: Sequence[str], k: int) -> float:
    if k < 1:
        raise ValueError("k must be positive")
    if not relevant:
        raise ValueError("recall requires at least one relevant document")
    top_k = _deduplicate(ranking)[:k]
    return len(relevant.intersection(top_k)) / len(relevant)


def reciprocal_rank_at_k(relevant: set[str], ranking: Sequence[str], k: int) -> float:
    if k < 1:
        raise ValueError("k must be positive")
    for rank, document_id in enumerate(_deduplicate(ranking)[:k], start=1):
        if document_id in relevant:
            return 1 / rank
    return 0.0


def ndcg_at_k(relevance: dict[str, int], ranking: Sequence[str], k: int) -> float:
    if k < 1:
        raise ValueError("k must be positive")
    if not relevance:
        raise ValueError("NDCG requires graded relevance judgments")

    def discounted_gain(grades: Sequence[int]) -> float:
        return sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, 1))

    actual_grades = [relevance.get(document_id, 0) for document_id in _deduplicate(ranking)[:k]]
    ideal_grades = sorted(relevance.values(), reverse=True)[:k]
    ideal = discounted_gain(ideal_grades)
    return discounted_gain(actual_grades) / ideal if ideal else 0.0


def evaluate_rankings(
    examples: Iterable[RetrievalExample],
    rankings: dict[str, Sequence[str]],
    *,
    k_values: Sequence[int] = (1, 3, 5, 10),
) -> dict[str, Any]:
    ks = tuple(dict.fromkeys(k_values))
    if not ks or any(k < 1 for k in ks):
        raise ValueError("k_values must contain positive integers")

    per_query: list[dict[str, Any]] = []
    relevant_rows: list[dict[str, Any]] = []
    abstention_outcomes: list[bool] = []
    for example in examples:
        ranking = _deduplicate(rankings.get(example.query_id, ()))
        if example.should_abstain:
            outcome = len(ranking) == 0
            abstention_outcomes.append(outcome)
            per_query.append(
                {
                    "query_id": example.query_id,
                    "should_abstain": True,
                    "abstention_correct": outcome,
                    "retrieved_documents": ranking,
                }
            )
            continue

        relevant = set(example.relevant_documents)
        row = {
            "query_id": example.query_id,
            "query_type": example.query_type.value,
            "should_abstain": False,
            "relevant_documents": example.relevant_documents,
            "retrieved_documents": ranking,
            "precision_at_k": {str(k): precision_at_k(relevant, ranking, k) for k in ks},
            "recall_at_k": {str(k): recall_at_k(relevant, ranking, k) for k in ks},
            "mrr_at_k": {str(k): reciprocal_rank_at_k(relevant, ranking, k) for k in ks},
            "ndcg_at_k": {str(k): ndcg_at_k(example.relevant_documents, ranking, k) for k in ks},
        }
        relevant_rows.append(row)
        per_query.append(row)

    if not relevant_rows:
        raise ValueError("evaluation requires at least one non-abstention example")

    def macro_average(metric: str) -> dict[str, float]:
        return {
            str(k): sum(row[metric][str(k)] for row in relevant_rows) / len(relevant_rows)
            for k in ks
        }

    return {
        "evaluated_queries": len(per_query),
        "relevance_queries": len(relevant_rows),
        "abstention_queries": len(abstention_outcomes),
        "precision_at_k": macro_average("precision_at_k"),
        "recall_at_k": macro_average("recall_at_k"),
        "mrr_at_k": macro_average("mrr_at_k"),
        "ndcg_at_k": macro_average("ndcg_at_k"),
        "abstention_accuracy": (
            sum(abstention_outcomes) / len(abstention_outcomes) if abstention_outcomes else None
        ),
        "per_query": per_query,
    }
