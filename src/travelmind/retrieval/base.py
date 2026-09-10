from typing import Protocol

from travelmind.schemas import Evidence


class Retriever(Protocol):
    """A replaceable retrieval boundary for dense, sparse, or hybrid implementations."""

    def search(self, queries: list[str], *, limit: int) -> list[Evidence]: ...


class InMemoryRetriever:
    """Deterministic adapter for demos and tests; not a production retrieval strategy."""

    def __init__(self, documents: list[Evidence]) -> None:
        self._documents = documents

    def search(self, queries: list[str], *, limit: int) -> list[Evidence]:
        if not queries:
            return []
        return sorted(self._documents, key=lambda item: item.score, reverse=True)[:limit]
