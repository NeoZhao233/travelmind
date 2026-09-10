from __future__ import annotations

import hashlib
import math
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from travelmind.retrieval.models import RetrievalHit, SearchResponse
from travelmind.schemas import Evidence

BGE_RERANKER_BASE = "BAAI/bge-reranker-base"


class RerankerDependencyError(RuntimeError):
    """Raised when the optional reranking runtime is unavailable."""


class RerankerInferenceError(RuntimeError):
    """Raised when reranking cannot produce one valid score per candidate."""


class RerankerProvider(Protocol):
    model_name: str

    def score(self, query: str, documents: list[str]) -> list[float]: ...

    def runtime_metadata(self) -> dict[str, Any]: ...


def validate_scores(scores: list[float], *, expected: int) -> None:
    if len(scores) != expected:
        raise RerankerInferenceError(
            f"Reranker returned {len(scores)} scores for {expected} candidates"
        )
    if not all(math.isfinite(score) for score in scores):
        raise RerankerInferenceError("Reranker returned a non-finite score")


class FastEmbedCrossEncoderProvider:
    """Versioned FastEmbed adapter for the multilingual BGE cross-encoder."""

    def __init__(
        self,
        *,
        model_name: str = BGE_RERANKER_BASE,
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
            # FastEmbed 0.8.0 contains this implementation but does not export it at top level.
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as exc:
            raise RerankerDependencyError(
                "Reranking requires the optional dependency: ./scripts/bootstrap.sh --extra dense"
            ) from exc

        supported = {item["model"]: item for item in TextCrossEncoder.list_supported_models()}
        if model_name not in supported:
            raise RerankerInferenceError(f"FastEmbed does not support reranker {model_name}")

        self.model_name = model_name
        self._model_registry_entry = supported[model_name]
        self._cache_dir = cache_dir
        self._fastembed_version = version("fastembed")
        try:
            self._model = TextCrossEncoder(
                model_name=model_name,
                cache_dir=str(cache_dir) if cache_dir else None,
                local_files_only=local_files_only,
            )
        except Exception as exc:
            mode = "local cache" if local_files_only else "configured model source"
            raise RerankerInferenceError(
                f"Could not load reranker {model_name} from {mode}: {exc}"
            ) from exc
        self._artifact_fingerprint = self._fingerprint_cached_artifact()

    def _fingerprint_cached_artifact(self) -> str | None:
        if self._cache_dir is None:
            return None
        model_file = Path(str(self._model_registry_entry.get("model_file", "")))
        if not model_file.parts:
            return None
        model_slug = self.model_name.rsplit("/", maxsplit=1)[-1]
        candidates = [
            path for path in self._cache_dir.rglob(str(model_file)) if model_slug in str(path)
        ]
        if not candidates:
            return None
        artifact_root = sorted(candidates)[0]
        for _ in model_file.parts:
            artifact_root = artifact_root.parent
        digest = hashlib.sha256()
        for path in sorted(item for item in artifact_root.rglob("*") if item.is_file()):
            digest.update(str(path.relative_to(artifact_root)).encode())
            digest.update(b"\0")
            with path.open("rb") as artifact:
                for block in iter(lambda: artifact.read(1024 * 1024), b""):
                    digest.update(block)
            digest.update(b"\0")
        return digest.hexdigest()

    def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        try:
            scores = [float(score) for score in self._model.rerank(query, documents)]
        except Exception as exc:
            raise RerankerInferenceError(f"Cross-encoder inference failed: {exc}") from exc
        validate_scores(scores, expected=len(documents))
        return scores

    def runtime_metadata(self) -> dict[str, Any]:
        return {
            "provider": "fastembed_cross_encoder",
            "fastembed_version": self._fastembed_version,
            "model_name": self.model_name,
            "registered_description": self._model_registry_entry.get("description"),
            "registered_license": self._model_registry_entry.get("license"),
            "registered_size_gb": self._model_registry_entry.get("size_in_GB"),
            "registered_sources": self._model_registry_entry.get("sources", {}),
            "registered_model_file": self._model_registry_entry.get("model_file"),
            "cached_artifact_sha256": self._artifact_fingerprint,
        }


class RerankingRetriever:
    """Rerank a bounded candidate set and preserve base order on reranker failure."""

    def __init__(
        self,
        *,
        base: Any,
        reranker: RerankerProvider,
        candidate_limit: int = 10,
        timeout_seconds: float = 5.0,
    ) -> None:
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._base = base
        self._reranker = reranker
        self._candidate_limit = candidate_limit
        self._timeout_seconds = timeout_seconds

    def _fallback(
        self,
        response: SearchResponse,
        *,
        limit: int,
        status: str,
        latency_ms: float,
        error_type: str | None = None,
    ) -> SearchResponse:
        diagnostics = dict(response.diagnostics)
        degraded = list(diagnostics.get("degraded_components", []))
        fallbacks = list(diagnostics.get("fallbacks_used", []))
        degraded.append("reranker")
        fallbacks.append("preserve_base_order")
        reranker_diagnostics: dict[str, Any] = {
            "status": status,
            "latency_ms": latency_ms,
            "candidate_count": len(response.hits),
        }
        if error_type is not None:
            reranker_diagnostics["error_type"] = error_type
        diagnostics.update(
            {
                "degraded_components": list(dict.fromkeys(degraded)),
                "fallbacks_used": list(dict.fromkeys(fallbacks)),
                "reranker": reranker_diagnostics,
            }
        )
        return SearchResponse(
            hits=response.hits[:limit],
            unsupported_filters=response.unsupported_filters,
            candidate_documents=response.candidate_documents,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _candidate_text(hit: RetrievalHit) -> str:
        tags = hit.metadata.get("tags", [])
        tag_text = " ".join(str(tag) for tag in tags) if isinstance(tags, list) else ""
        return " ".join(
            part
            for part in (
                str(hit.metadata.get("place_name", "")),
                str(hit.metadata.get("source_title", "")),
                str(hit.metadata.get("source_section", "")),
                tag_text,
                hit.content,
            )
            if part.strip()
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
        response = self._base.rank(
            query,
            limit=max(limit, self._candidate_limit),
            filters=filters,
        )
        candidates = list(response.hits[: self._candidate_limit])
        if not candidates:
            diagnostics = dict(response.diagnostics)
            diagnostics["reranker"] = {
                "status": "skipped_empty",
                "latency_ms": 0.0,
                "candidate_count": 0,
            }
            return SearchResponse(
                hits=(),
                unsupported_filters=response.unsupported_filters,
                candidate_documents=response.candidate_documents,
                diagnostics=diagnostics,
            )

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reranker")
        started = perf_counter()
        future = executor.submit(
            self._reranker.score,
            query,
            [self._candidate_text(hit) for hit in candidates],
        )
        try:
            scores = future.result(timeout=self._timeout_seconds)
            latency_ms = (perf_counter() - started) * 1000
            validate_scores(scores, expected=len(candidates))
        except TimeoutError:
            future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            return self._fallback(
                response,
                limit=limit,
                status="timeout",
                latency_ms=self._timeout_seconds * 1000,
            )
        except Exception as exc:
            executor.shutdown(wait=False, cancel_futures=True)
            return self._fallback(
                response,
                limit=limit,
                status="error",
                latency_ms=(perf_counter() - started) * 1000,
                error_type=type(exc).__name__,
            )
        else:
            executor.shutdown(wait=False, cancel_futures=True)

        ranked = sorted(
            zip(candidates, scores, range(1, len(candidates) + 1), strict=True),
            key=lambda item: (-item[1], item[2]),
        )
        reranked_hits = tuple(
            RetrievalHit(
                document_id=hit.document_id,
                chunk_id=hit.chunk_id,
                score=score,
                content=hit.content,
                source_url=hit.source_url,
                metadata={
                    **hit.metadata,
                    "pre_rerank_rank": previous_rank,
                    "pre_rerank_score": hit.score,
                    "reranker_score": score,
                },
            )
            for hit, score, previous_rank in ranked[:limit]
        )
        diagnostics = dict(response.diagnostics)
        base_mode = str(diagnostics.get("retrieval_mode", "base"))
        diagnostics.update(
            {
                "retrieval_mode": f"{base_mode}_reranked",
                "reranker": {
                    "status": "success",
                    "latency_ms": latency_ms,
                    "candidate_count": len(candidates),
                },
            }
        )
        return SearchResponse(
            hits=reranked_hits,
            unsupported_filters=response.unsupported_filters,
            candidate_documents=response.candidate_documents,
            diagnostics=diagnostics,
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
                    "score_type": "cross_encoder",
                    **hit.metadata,
                },
            )
            for hit in response.hits
        ]
