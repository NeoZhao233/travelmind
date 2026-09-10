# ADR 007: BGE-small-zh-v1.5, FastEmbed, and Qdrant for the dense baseline

## Status

Accepted for Stage 2B; production deployment mode remains open.

## Problem

The travel corpus is Chinese and the lexical baseline misses paraphrases. The dense channel needs a
Chinese-capable model, reproducible CPU inference, an injectable test boundary, and a vector store
that can later support hybrid search and payload filters.

## Decision

Use `BAAI/bge-small-zh-v1.5` with FastEmbed 0.8.0 and Qdrant cosine search. Add
`为这个句子生成表示以用于检索相关文章：` only to queries. Keep FastEmbed optional so sparse-only
development and fallback do not require ONNX or model weights. Use Qdrant local memory mode for the
metric baseline and retain the same adapter boundary for a server deployment later.

The model is explicitly versioned in its ID, FastEmbed is pinned in `uv.lock`, and every report
includes runtime metadata plus a cached-artifact SHA-256 fingerprint.

## Why this combination

- The model is specifically listed as Chinese, 512-dimensional, MIT-licensed, and small enough for
  local CPU iteration.
- FastEmbed uses a lighter ONNX runtime instead of bringing the full PyTorch training stack into the
  serving path.
- Qdrant is already the project's intended vector database and supports local development without
  forcing Docker into every unit test.
- Explicit embedding generation keeps vector validation and provider failure injection under
  project control.

## Alternatives considered

- **BGE-base/large or BGE-M3.** Potentially stronger, but higher model size and latency should only
  be paid after a small baseline exposes where capacity is needed.
- **OpenAI or another hosted embedding API.** Operationally simple and scalable, but adds recurring
  cost, network/privacy concerns, provider drift, and API availability to the first dense baseline.
- **SentenceTransformers/FlagEmbedding with PyTorch.** Richer training and GPU controls, but a much
  heavier dependency footprint for CPU-only inference.
- **NumPy cosine search only.** Adequate for 14 chunks, but would postpone the payload, point-ID, and
  vector-dimension contracts that the production store needs.
- **Qdrant implicit FastEmbed integration.** Concise, but makes the embedding boundary harder to fake
  and validate independently in failure tests.

## Consequences

- First-time use needs network access and a roughly 90MB ignored model cache.
- Cached inference can be forced offline with `--local-files-only`.
- Qdrant local-mode latency cannot be extrapolated to a remote service.
- Cosine and BM25 scores have different ranges; RRF is preferred over raw-score addition.
- Similarity thresholds must be calibrated on project data rather than copied from a model card.
- Single-channel dense failure is explicit now; automatic BM25 degradation belongs to Stage 2C.

## Interview prompts

- Why choose the small Chinese BGE model before BGE-M3?
- Why add an instruction to queries but not documents?
- Why FastEmbed instead of SentenceTransformers?
- Why inject the embedding provider instead of using Qdrant's implicit inference API?
- What does cosine similarity measure, and why can its raw value not be compared with BM25?
- What does local Qdrant validate, and what production behavior does it not validate?
- How do model ID, package lock, and artifact hash address different sources of drift?
