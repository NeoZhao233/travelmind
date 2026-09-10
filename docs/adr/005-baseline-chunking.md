# ADR 005: Use structure-aware character chunking as the baseline

## Status

Accepted as a baseline; subject to Stage 2 ablation.

## Problem

Retrieval requires bounded text units, but choosing semantic chunking before a benchmark exists can
add model cost and nondeterminism without evidence of a quality gain. Fixed-width splitting can
also separate a travel rule from its exception.

## Decision

Normalize Unicode with NFKC, preserve paragraph boundaries, split oversized paragraphs on Chinese
or English sentence punctuation where possible, and pack units up to 500 characters. Do not add
overlap in the baseline. Derive each chunk ID from its document ID and normalized content hash.

The stored `token_estimate` uses `ceil(character_count / 2)` only for rough budgeting. Actual model
limits and cost measurements must use the selected model's tokenizer later.

## Alternatives considered

- **Fixed token windows.** Better aligned with model limits, but tokenizer-specific and still
  ignores section structure.
- **Overlapping windows.** Can protect boundary recall, but duplicates evidence, increases index and
  reranking cost, and can inflate apparent recall.
- **LLM or embedding semantic chunking.** May preserve meaning, but is slower, harder to reproduce,
  and needs an evaluation result to justify operational cost.
- **One document per chunk.** Preserves context but produces noisy retrieval and can exceed context
  budgets as source sections grow.

## Consequences

- Ingestion is deterministic, local, and does not require an API key.
- Content edits create a new chunk ID while unchanged content keeps its ID.
- Document-level labels remain stable across future chunking experiments.
- The current short seed documents each produce one chunk; this does not validate the 500-character
  value for a production corpus.

## Planned ablation

Compare character size, tokenizer-aware windows, overlap, parent-child retrieval, and semantic
chunking on the same document-level labels. Report retrieval quality together with chunk count,
index size, latency, and reranking/token cost.

## Interview prompts

- Why is 500 characters not claimed as an optimal value?
- Why can overlap make offline metrics misleading?
- What changes should and should not change a chunk ID?
- Why is a tokenizer-specific count deferred?
