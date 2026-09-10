# Stage 4D: deduplication, conflict handling, and extractive compression

## Pipeline

```text
retrieved evidence
  -> value-aware lexical near-duplicate grouping
  -> authority/freshness conflict policy
  -> critical-fact extractive compression
  -> Stage 4C coverage-aware budget packing
```

The refiner operates before token packing. Its trace contains IDs, actions, counts, and reason codes,
but no evidence text.

## Deduplication

Normalized lexical similarity groups exact and near duplicates at a 0.92 threshold. The winner is
chosen by authority, observation time, then retrieval priority; all document IDs are retained in
`merged_document_ids` for provenance.

Structured facts with the same key but different values are never deduplicated, even when their text
is almost identical. They must reach the conflict policy. This prevents `17:00` and `18:00` from
being silently treated as copies.

This baseline intentionally does not claim semantic paraphrase deduplication. An embedding or
cross-encoder candidate must later beat this deterministic policy without merging distinct facts.

## Conflict policy

For different values of the same `fact_key`:

1. prefer the higher-authority source;
2. for equal authority, prefer a strictly newer valid observation;
3. otherwise retain every value and mark the conflict `unresolved`.

Retrieval rank cannot resolve a factual conflict. A newer third-party page also cannot override an
older official source merely because of recency. Production dynamic facts additionally require a
freshness SLA; authority alone is not proof that an old fact is still valid.

## Compression

Compression is extractive rather than generative. Whole source sentences receive deterministic
scores for requested aspects and critical anchors such as numbers, prices, negation, closure,
exceptions, and requirements. Selected sentences retain their original order and document ID.

Compared with head truncation, this avoids systematically deleting key facts that occur near the end
of a source. If no whole sentence fits, compression is skipped and the downstream Stage 4B packer
applies its existing clip/drop policy; the skip is traced.

## Controlled evaluation

The seven versioned cases isolate exact duplicate, near duplicate, authority conflict, freshness
conflict, unresolved conflict, and two late-critical-fact compression scenarios.

| Metric | Result |
| --- | ---: |
| Refinement decision accuracy | 1.000 (7/7) |
| Duplicate groups | 2 |
| Resolved conflicts | 2 |
| Safely unresolved conflicts | 1 |
| Head-truncation critical-fact preservation | 0.000 (0/4) |
| Extractive critical-fact preservation | 1.000 (4/4) |
| Estimated evidence-token reduction | 42.4% |

These are behavior-isolation cases deliberately containing late facts, not natural-traffic quality
claims. Stage 4F must test the selected full pipeline on a larger held-out answer/citation set.

## Reproduce

```bash
travelmind eval-context-refinement --root . \
  --output evals/results/context_refinement_controlled_v1_seed.json
```
