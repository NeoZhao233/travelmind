# ADR 019: deterministic evidence refinement before context packing

## Status

Accepted for the Stage 4D pilot.

## Decision

Use value-aware lexical near-duplicate detection, authority/freshness conflict precedence, and
extractive critical-fact compression before coverage-aware token packing. Preserve merged
provenance, and retain conflicting values whenever precedence is insufficient.

## Alternatives

- Embedding-only deduplication: detects paraphrases but can merge numerically different facts.
- Keep every duplicate: safest for recall but wastes budget and amplifies repeated claims.
- Let retrieval score decide conflicts: relevance is not factual authority or freshness.
- Always select the newest source: a recent third-party article should not silently override an
  official source.
- LLM summarization: more fluent, but can alter numbers, drop exceptions, add unsupported claims,
  and fail when the provider is unavailable.

## Consequences

The baseline is deterministic, cheap, auditable, and provider-independent. Lexical dedup misses
semantic paraphrases, metadata quality constrains conflict decisions, and extraction is less fluent
than abstraction. Those limitations remain explicit candidates for later measured improvements.
