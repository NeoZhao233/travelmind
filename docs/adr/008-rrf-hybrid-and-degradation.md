# ADR 008: Parallel BM25/dense retrieval with reciprocal rank fusion

## Status

Accepted for the Stage 2C baseline. Weight tuning and server-side execution remain open.

## Problem

BM25 and BGE retrieve complementary evidence, but their raw scores have different meanings and
scales. A hybrid path must combine them without pretending the scores are calibrated, keep latency
bounded, and remain useful when either dependency fails.

## Decision

Run BM25 and Qdrant dense retrieval concurrently, request ten document candidates from each, and
fuse document IDs with reciprocal rank fusion (RRF):

```text
score(document) = sum(1 / (k + rank_in_channel)), k = 60
```

Use rank only; preserve each channel's raw score as diagnostic metadata. If one channel errors or
times out, return the surviving channel through the same RRF contract and mark `sparse_only` or
`dense_only`. If neither channel returns a response, raise `HybridRetrievalError`; do not ask the
LLM to answer without evidence.

`k=60` is an untuned baseline. It is intentionally not optimized on the 15-query pilot because
there is no development/held-out split.

## Why RRF

- It does not require BM25 and cosine scores to be normalized or calibrated.
- A document retrieved by both channels is rewarded while a strong single-channel candidate is
  retained.
- Its behavior is deterministic, small enough to test directly, and easy to explain in an
  interview.
- It provides a stable pre-reranker baseline: later gains can be attributed to reranking rather
  than an opaque mixture of fusion changes.

## Why concurrent execution

The two channels are independent. Concurrent execution makes expected latency closer to the slower
channel than to the sum of both channels. The current two-thread runner is appropriate for local
blocking adapters. An async production service would use async clients or bounded worker pools and
provider-native deadlines.

## Alternatives considered

- **Add or average raw scores.** Invalid without calibration because BM25 is unbounded while cosine
  has a different range and distribution.
- **Min-max or z-score normalization.** Sensitive to the candidate set and outliers; per-query
  normalization can make scores look comparable without giving them the same relevance meaning.
- **Learned weighted fusion.** Can outperform RRF but needs a substantially larger, held-out set and
  adds overfitting and operational complexity.
- **Dense-only retrieval.** Removes the sparse service but regressed MRR@3 and several semantic
  first-rank cases on the pilot.
- **BM25-only retrieval.** Cheapest and strongest at some lexical cases, but missed paraphrases and
  had lower aggregate Recall@3.
- **Qdrant server-side fusion.** Attractive for production efficiency, but the in-process baseline
  keeps channel failures injectable and the fusion algorithm independently testable. Moving it
  server-side should preserve this response contract.
- **Cross-encoder immediately.** It would confound fusion and reranking effects. Reranking is a
  separate Stage 2D experiment with its own latency budget.

## Failure and safety boundaries

- Each channel records `success`, `error`, or `timeout`; exception messages are not copied because
  third-party text can contain request data or credentials.
- A fallback response carries `degraded_components` and `fallbacks_used`; fallback activation is an
  availability mechanism and an alert signal.
- A Python thread timeout stops waiting but cannot kill an already-running call. Qdrant and model
  service clients still need their own network/inference timeouts in production.
- Metadata filters are rejected until sparse and dense channels implement consistent semantics.
- Dual failure is fail-closed because uncited travel constraints must not be invented.

## Evidence

On dataset fingerprint
`a836d2edc0797b00e5ae0123c9167316d8baa1a0abd6211a27391ec211cf83f5`, RRF reached Recall@3
0.922, MRR@3 0.956, and NDCG@3 0.930. The detailed limitations and comparison are in
`docs/stage2c-hybrid-rrf.md`.
