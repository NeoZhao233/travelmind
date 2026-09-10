from pathlib import Path

import pytest

from travelmind.retrieval.bm25 import BM25Retriever

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def retriever() -> BM25Retriever:
    return BM25Retriever.from_project(PROJECT_ROOT)


def test_bm25_retrieves_paraphrased_gate_document_in_top_three(
    retriever: BM25Retriever,
) -> None:
    response = retriever.rank("故宫从哪个门进，从哪个门出？", limit=3)

    assert "palace-route-20260908" in {hit.document_id for hit in response.hits}
    assert all(hit.score > 0 for hit in response.hits)


def test_bm25_ranks_explicit_gate_names_first(retriever: BM25Retriever) -> None:
    response = retriever.rank("故宫午门神武门东华门", limit=3)

    assert response.hits[0].document_id == "palace-route-20260908"


def test_metadata_filters_select_free_no_booking_place(retriever: BM25Retriever) -> None:
    response = retriever.rank(
        "免费开放公园",
        filters={
            "district": "西城区",
            "category": "公园",
            "admission_max_cny": 0,
            "booking_required": False,
        },
    )

    assert response.candidate_documents == 1
    assert {hit.metadata["place_id"] for hit in response.hits} == {"shichahai-park"}


def test_unsupported_filter_is_reported_without_silent_strict_filtering(
    retriever: BM25Retriever,
) -> None:
    response = retriever.rank("故宫周一开放吗", filters={"weekday": "monday"})

    assert response.unsupported_filters == ("weekday",)
    assert response.hits


def test_empty_query_and_impossible_filter_fail_safely(retriever: BM25Retriever) -> None:
    assert retriever.rank("！？").hits == ()
    assert retriever.rank("博物馆", filters={"district": "不存在"}).hits == ()

    with pytest.raises(ValueError, match="positive"):
        retriever.rank("故宫", limit=0)
    with pytest.raises(ValueError, match="must be a boolean"):
        retriever.rank("故宫", filters={"booking_required": "no"})
