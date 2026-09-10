import pytest

from travelmind.domain.models import RetrievalExample
from travelmind.evaluation.metrics import (
    evaluate_rankings,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank_at_k,
)


def test_standard_metrics_use_document_level_relevance() -> None:
    relevant = {"a", "b"}
    ranking = ["x", "a", "b"]

    assert precision_at_k(relevant, ranking, 3) == pytest.approx(2 / 3)
    assert recall_at_k(relevant, ranking, 3) == 1.0
    assert reciprocal_rank_at_k(relevant, ranking, 3) == 0.5
    assert 0 < ndcg_at_k({"a": 3, "b": 1}, ranking, 3) < 1


def test_duplicate_retrieved_ids_do_not_inflate_metrics() -> None:
    assert precision_at_k({"a"}, ["a", "a", "x"], 2) == 0.5
    assert recall_at_k({"a"}, ["a", "a"], 2) == 1.0


def test_evaluator_separates_abstention_from_relevance_metrics() -> None:
    answerable = RetrievalExample(
        query_id="answerable",
        query="故宫入口",
        query_type="exact",
        relevant_documents={"route": 3},
        annotator="test",
    )
    abstention = RetrievalExample(
        query_id="no-answer",
        query="不存在的信息",
        query_type="exact",
        should_abstain=True,
        annotator="test",
    )

    result = evaluate_rankings(
        [answerable, abstention],
        {"answerable": ["route"], "no-answer": []},
        k_values=(1,),
    )

    assert result["recall_at_k"]["1"] == 1.0
    assert result["abstention_accuracy"] == 1.0
    assert result["abstention_queries"] == 1
