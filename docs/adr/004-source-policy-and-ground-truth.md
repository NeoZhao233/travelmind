# ADR 004: Source authority, freshness, and document-level ground truth

## Status

Accepted for the Stage 1 corpus.

## Problem

Travel answers mix descriptive facts with volatile opening hours, prices, and booking rules. Search
quality cannot be evaluated if source trust, collection time, and relevance labels are implicit.
Chunk-level labels also become obsolete every time the chunking strategy changes.

## Decision

Use this source preference order:

1. official venue or operator;
2. government authority;
3. official aggregator;
4. third party only when higher-authority coverage is unavailable.

Every source document records authority, freshness class, collection time, optional source update
date, and optional validity range. `static` covers slow-changing descriptions, `seasonal` covers
recurring calendar rules, and `dynamic` covers values that need close-to-use verification.

Retrieval ground truth is graded at document-section level: 3 means directly answers the query, 2
means materially useful, and 1 means supporting context. Expected places, hard filters, and fact
types are stored separately so retrieval and downstream constraint correctness can be diagnosed.

## Alternatives considered

- **Use any top web-search result.** Faster to collect, but ranking is not authority and conflicting
  copies often omit update dates.
- **Store only normalized facts.** Good for filtering, but loses explanatory context and source
  passages required for grounded generation.
- **Store only raw text.** Simple, but numeric and temporal constraints remain hard to validate
  deterministically.
- **Label chunks directly.** Precise for one index build, but label IDs change during chunking
  ablations and confound the comparison.
- **Use binary relevance.** Easier to annotate, but cannot distinguish direct answers from useful
  supporting material for MRR/NDCG-style analysis.

## Consequences

- A source can be retrieved as text and also contribute typed facts.
- The system can prefer authority and freshness during filtering or reranking.
- Chunking experiments map retrieved chunks back to stable source documents for evaluation.
- A higher-authority source is not assumed fresh merely because it is official; stale dynamic facts
  must still be rechecked or treated as unknown.
- Human review remains a bottleneck and label quality must be measured as the dataset grows.

## Fallback boundary

When volatile sources are missing, stale, or contradictory, the safe behavior is to return unknown
or request pre-trip confirmation. It is unsafe to silently substitute an old third-party price or
opening time. Descriptive recommendations may continue when their evidence remains applicable.

## Interview prompts

- Why is source authority different from freshness?
- Why keep both source passages and normalized facts?
- Why label documents instead of generated chunks?
- How would you measure annotator agreement and resolve conflicts?
- When should retrieval fail closed rather than degrade to a lower-authority source?
