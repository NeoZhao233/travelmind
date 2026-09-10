from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models

from travelmind.domain.models import Chunk, PlaceRecord, SourceDocument
from travelmind.ingestion.chunking import chunk_documents
from travelmind.ingestion.dataset import load_jsonl, validate_seed_dataset
from travelmind.retrieval.corpus import build_searchable_text
from travelmind.retrieval.embeddings import EmbeddingProvider, validate_vector
from travelmind.retrieval.models import RetrievalHit, SearchResponse
from travelmind.retrieval.tokenization import tokenize_for_lexical_search
from travelmind.schemas import Evidence

_POINT_NAMESPACE = uuid.UUID("8aac562a-468c-4c9e-b0ba-1bd2bc5e487e")


class DenseIndexError(RuntimeError):
    """Raised when embeddings cannot be published to the vector index."""


class DenseRetrievalError(RuntimeError):
    """Raised when the dense query path fails after index construction."""


class QdrantDenseRetriever:
    """Dense retrieval over an injected embedding provider and Qdrant client."""

    def __init__(
        self,
        *,
        places: list[PlaceRecord],
        documents: list[SourceDocument],
        chunks: list[Chunk],
        embedder: EmbeddingProvider,
        client: QdrantClient | None = None,
        collection_name: str = "travelmind_dense",
    ) -> None:
        if not documents or not chunks:
            raise DenseIndexError("Dense retrieval requires at least one document and chunk")
        self._embedder = embedder
        self._client = client or QdrantClient(":memory:")
        self._collection_name = collection_name
        self._chunk_count = len(chunks)
        place_by_id = {place.place_id: place for place in places}
        document_by_id = {document.document_id: document for document in documents}

        texts: list[str] = []
        payloads: list[dict[str, Any]] = []
        for chunk in chunks:
            document = document_by_id.get(chunk.document_id)
            place = place_by_id.get(chunk.place_id)
            if document is None or place is None:
                raise DenseIndexError(f"Chunk {chunk.chunk_id} has unresolved references")
            texts.append(build_searchable_text(place, document, chunk))
            payloads.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": document.document_id,
                    "place_id": place.place_id,
                    "place_name": place.name,
                    "source_title": document.title,
                    "source_section": document.section,
                    "tags": list(document.tags),
                    "content": chunk.content,
                    "source_url": str(document.source_url),
                    "authority": document.authority.value,
                    "freshness": document.freshness.value,
                }
            )

        try:
            vectors = embedder.embed_documents(texts)
            if len(vectors) != len(chunks):
                raise DenseIndexError(
                    f"Embedding count {len(vectors)} does not match chunk count {len(chunks)}"
                )
            for index, vector in enumerate(vectors):
                validate_vector(
                    vector,
                    dimension=embedder.dimension,
                    label=f"index[{index}]",
                )
            self._client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=embedder.dimension,
                    distance=models.Distance.COSINE,
                ),
            )
            self._client.upsert(
                collection_name=collection_name,
                points=[
                    models.PointStruct(
                        id=str(uuid.uuid5(_POINT_NAMESPACE, chunk.chunk_id)),
                        vector=vector,
                        payload=payload,
                    )
                    for chunk, vector, payload in zip(chunks, vectors, payloads, strict=True)
                ],
                wait=True,
            )
        except DenseIndexError:
            raise
        except Exception as exc:
            raise DenseIndexError(f"Failed to build Qdrant dense index: {exc}") from exc

    @classmethod
    def from_project(
        cls,
        root: Path,
        *,
        embedder: EmbeddingProvider,
        client: QdrantClient | None = None,
        collection_name: str = "travelmind_dense",
    ) -> QdrantDenseRetriever:
        root = root.resolve()
        validate_seed_dataset(root)
        places = load_jsonl(root / "data/seed/places.jsonl", PlaceRecord)
        documents = load_jsonl(root / "data/seed/documents.jsonl", SourceDocument)
        return cls(
            places=places,
            documents=documents,
            chunks=chunk_documents(documents),
            embedder=embedder,
            client=client,
            collection_name=collection_name,
        )

    def rank(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> SearchResponse:
        if limit < 1:
            raise ValueError("limit must be positive")
        unsupported_filters = tuple(sorted(filters or {}))
        if not tokenize_for_lexical_search(query):
            return SearchResponse((), unsupported_filters, 0)

        try:
            vector = self._embedder.embed_query(query)
            validate_vector(vector, dimension=self._embedder.dimension, label="query")
            points = self._client.query_points(
                collection_name=self._collection_name,
                query=vector,
                limit=min(self._chunk_count, max(limit * 4, limit)),
                with_payload=True,
                with_vectors=False,
            ).points
        except Exception as exc:
            raise DenseRetrievalError(f"Qdrant dense query failed: {exc}") from exc

        best_by_document: dict[str, RetrievalHit] = {}
        for point in points:
            payload = point.payload or {}
            document_id = str(payload.get("document_id", ""))
            chunk_id = str(payload.get("chunk_id", ""))
            if not document_id or not chunk_id:
                raise DenseRetrievalError("Qdrant result is missing document or chunk identity")
            hit = RetrievalHit(
                document_id=document_id,
                chunk_id=chunk_id,
                score=float(point.score),
                content=str(payload.get("content", "")),
                source_url=str(payload.get("source_url", "")),
                metadata={
                    "place_id": payload.get("place_id"),
                    "place_name": payload.get("place_name"),
                    "source_title": payload.get("source_title"),
                    "source_section": payload.get("source_section"),
                    "tags": payload.get("tags", []),
                    "authority": payload.get("authority"),
                    "freshness": payload.get("freshness"),
                },
            )
            previous = best_by_document.get(document_id)
            if previous is None or hit.score > previous.score:
                best_by_document[document_id] = hit

        hits = tuple(
            sorted(
                best_by_document.values(),
                key=lambda hit: (-hit.score, hit.document_id),
            )[:limit]
        )
        return SearchResponse(hits, unsupported_filters, len(best_by_document))

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
                    "score_type": "cosine_similarity",
                    **hit.metadata,
                },
            )
            for hit in response.hits
        ]
