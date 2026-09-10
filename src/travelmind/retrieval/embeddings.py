from __future__ import annotations

import hashlib
import math
import os
from importlib.metadata import version
from pathlib import Path
from typing import Any, Protocol

BGE_SMALL_ZH_V15 = "BAAI/bge-small-zh-v1.5"
BGE_ZH_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class DenseDependencyError(RuntimeError):
    """Raised when the optional dense runtime is not installed."""


class DenseEmbeddingError(RuntimeError):
    """Raised when a model cannot load or returns invalid embeddings."""


class EmbeddingProvider(Protocol):
    model_name: str
    dimension: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...

    def runtime_metadata(self) -> dict[str, Any]: ...


def validate_vector(vector: list[float], *, dimension: int, label: str) -> None:
    if len(vector) != dimension:
        raise DenseEmbeddingError(
            f"{label} embedding dimension {len(vector)} does not match expected {dimension}"
        )
    if not vector or not all(math.isfinite(value) for value in vector):
        raise DenseEmbeddingError(f"{label} embedding contains non-finite or empty values")
    if not any(value != 0 for value in vector):
        raise DenseEmbeddingError(f"{label} embedding must not be an all-zero vector")


class FastEmbedProvider:
    """Version-recorded FastEmbed adapter for the Chinese BGE dense baseline."""

    def __init__(
        self,
        *,
        model_name: str = BGE_SMALL_ZH_V15,
        cache_dir: Path | None = None,
        local_files_only: bool = False,
    ) -> None:
        os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            huggingface_cache = cache_dir / "huggingface"
            os.environ.setdefault("HF_HOME", str(huggingface_cache))
            os.environ.setdefault("HF_XET_CACHE", str(huggingface_cache / "xet"))
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise DenseDependencyError(
                "Dense retrieval requires the optional dependency: "
                "./scripts/bootstrap.sh --extra dense"
            ) from exc

        supported_entries = {item["model"]: item for item in TextEmbedding.list_supported_models()}
        supported = {name: int(item["dim"]) for name, item in supported_entries.items()}
        if model_name not in supported:
            raise DenseEmbeddingError(f"FastEmbed does not support model {model_name}")

        self.model_name = model_name
        self.dimension = supported[model_name]
        self._model_registry_entry = supported_entries[model_name]
        self._cache_dir = cache_dir
        self._fastembed_version = version("fastembed")
        try:
            self._model = TextEmbedding(
                model_name=model_name,
                cache_dir=str(cache_dir) if cache_dir else None,
                local_files_only=local_files_only,
            )
        except Exception as exc:
            mode = "local cache" if local_files_only else "configured model source"
            raise DenseEmbeddingError(f"Could not load {model_name} from {mode}: {exc}") from exc
        self._artifact_fingerprint = self._fingerprint_cached_artifact()

    def _fingerprint_cached_artifact(self) -> str | None:
        if self._cache_dir is None:
            return None
        model_file = str(self._model_registry_entry.get("model_file", ""))
        model_slug = self.model_name.rsplit("/", maxsplit=1)[-1]
        candidates = (
            [path for path in self._cache_dir.rglob(model_file) if model_slug in str(path.parent)]
            if model_file
            else []
        )
        if not candidates:
            return None
        model_dir = sorted(candidates)[0].parent
        digest = hashlib.sha256()
        for path in sorted(item for item in model_dir.rglob("*") if item.is_file()):
            digest.update(str(path.relative_to(model_dir)).encode())
            digest.update(b"\0")
            with path.open("rb") as artifact:
                for block in iter(lambda: artifact.read(1024 * 1024), b""):
                    digest.update(block)
            digest.update(b"\0")
        return digest.hexdigest()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            vectors = [vector.tolist() for vector in self._model.embed(texts)]
        except Exception as exc:
            raise DenseEmbeddingError(f"Document embedding failed: {exc}") from exc
        if len(vectors) != len(texts):
            raise DenseEmbeddingError(
                f"Embedding provider returned {len(vectors)} vectors for {len(texts)} documents"
            )
        for index, vector in enumerate(vectors):
            validate_vector(vector, dimension=self.dimension, label=f"document[{index}]")
        return vectors

    def embed_query(self, text: str) -> list[float]:
        instructed = f"{BGE_ZH_QUERY_INSTRUCTION}{text}"
        try:
            vectors = [vector.tolist() for vector in self._model.embed([instructed])]
        except Exception as exc:
            raise DenseEmbeddingError(f"Query embedding failed: {exc}") from exc
        if len(vectors) != 1:
            raise DenseEmbeddingError("Embedding provider did not return exactly one query vector")
        validate_vector(vectors[0], dimension=self.dimension, label="query")
        return vectors[0]

    def runtime_metadata(self) -> dict[str, Any]:
        return {
            "provider": "fastembed",
            "fastembed_version": self._fastembed_version,
            "model_name": self.model_name,
            "dimension": self.dimension,
            "query_instruction": BGE_ZH_QUERY_INSTRUCTION,
            "registered_sources": self._model_registry_entry.get("sources", {}),
            "registered_model_file": self._model_registry_entry.get("model_file"),
            "cached_artifact_sha256": self._artifact_fingerprint,
        }
