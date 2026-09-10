# ADR 017: deterministic fail-closed context budgeting

## Status

Accepted for Stage 4B.

## Decision

Reserve output and safety tokens before admitting evidence. Never truncate mandatory instructions,
the original request, or explicit constraints. Cap each evidence item, then clip or drop optional
items in retrieval order. Select the smallest pilot budget passing a fixed recall gate. After prompt
metadata was reduced to model-useful fields, the rerun selected 768 rather than 1024.

## Alternatives

- Rely on provider-side truncation: cheap to implement but silent and may remove the request or hard
  constraints.
- Always use the model's full context window: wastes tokens and increases distraction and cost.
- LLM summarization before a deterministic baseline: introduces latency, hallucination, and another
  outage path before its benefit can be measured.
- Use `tiktoken` as DeepSeek ground truth: tokenizer mismatch would create false precision.

## Consequences

The heuristic intentionally over-reserves capacity and must later be calibrated against provider
usage. Fixed-order clipping reduces relevant-document recall, creating a measurable Stage 4C target.
