from pathlib import Path

import pytest

from travelmind.retrieval.dense import (
    DenseIndexError,
    DenseRetrievalError,
    QdrantDenseRetriever,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class KeywordEmbeddingProvider:
    model_name = "test-keyword-embedding"
    dimension = 4

    def __init__(self, *, fail_query: bool = False) -> None:
        self.fail_query = fail_query

    @staticmethod
    def _vector(text: str) -> list[float]:
        gate_terms = ("入口", "午门", "神武门", "东华门", "进")
        if any(term in text for term in gate_terms):
            return [1.0, 0.0, 0.0, 0.0]
        if any(term in text for term in ("预约", "实名")):
            return [0.0, 1.0, 0.0, 0.0]
        if any(term in text for term in ("园林", "湖景", "昆明湖")):
            return [0.0, 0.0, 1.0, 0.0]
        return [0.0, 0.0, 0.0, 1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        if self.fail_query:
            raise RuntimeError("injected embedding outage")
        return self._vector(text)

    def runtime_metadata(self) -> dict[str, str | int]:
        return {"provider": "test", "model_name": self.model_name, "dimension": self.dimension}


class WrongDimensionProvider(KeywordEmbeddingProvider):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def test_qdrant_dense_retriever_bridges_semantic_gate_terms() -> None:
    retriever = QdrantDenseRetriever.from_project(
        PROJECT_ROOT,
        embedder=KeywordEmbeddingProvider(),
    )

    response = retriever.rank("故宫从哪里进，参观完从哪里出？", limit=3)

    assert response.hits[0].document_id == "palace-route-20260908"
    assert response.hits[0].metadata["place_id"] == "palace-museum"


def test_dense_index_rejects_embedding_dimension_mismatch() -> None:
    with pytest.raises(DenseIndexError, match="dimension"):
        QdrantDenseRetriever.from_project(
            PROJECT_ROOT,
            embedder=WrongDimensionProvider(),
        )


def test_dense_query_outage_is_wrapped_for_hybrid_fallback() -> None:
    retriever = QdrantDenseRetriever.from_project(
        PROJECT_ROOT,
        embedder=KeywordEmbeddingProvider(fail_query=True),
    )

    with pytest.raises(DenseRetrievalError, match="injected embedding outage"):
        retriever.rank("故宫入口")


def test_dense_empty_query_and_filters_are_explicit() -> None:
    retriever = QdrantDenseRetriever.from_project(
        PROJECT_ROOT,
        embedder=KeywordEmbeddingProvider(),
    )

    assert retriever.rank("！？").hits == ()
    response = retriever.rank("故宫", filters={"district": "东城区"})
    assert response.unsupported_filters == ("district",)
