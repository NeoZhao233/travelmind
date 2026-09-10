# Stage 2A: BM25 retrieval and evaluation baseline

## Outcome

Stage 2A establishes the first real retrieval baseline. It includes deterministic Chinese lexical
tokenization, an in-process BM25 index, selected metadata filters, document-level evaluation,
dataset fingerprinting, latency sampling, per-query diagnostics, and a CLI report writer.

This is a diagnostic baseline, not the completion of Stage 2. Dense retrieval, hybrid fusion, and
reranking remain next.

## Reproduce

```bash
travelmind eval-retrieval --root . \
  --output evals/results/bm25_lexical_seed.json

travelmind eval-retrieval --root . --apply-filters \
  --output evals/results/bm25_filtered_seed.json
```

The report records the four input files' SHA-256 fingerprint, BM25 parameters, tokenizer, cutoffs,
ranked document IDs and scores, per-query metrics, aggregate metrics, query-type breakdown, and
unsupported filters.

## Measured pilot result

The following values were generated on 2026-09-08 from the 15-query Stage 1 seed set at the report's
recorded fingerprint:

| Mode | P@1 | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR@3 | NDCG@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 lexical | 0.867 | 0.700 | 0.856 | 0.944 | 1.000 | 0.933 | 0.897 |
| BM25 + supported prefilters | 0.933 | 0.722 | 0.856 | 0.922 | 0.956 | 0.967 | 0.950 |

These numbers are reproducible measurements, but they are not resume-ready performance claims:
the corpus has only 14 documents, labels come from one annotator, no held-out split exists, and
there are no abstention examples. In-process sub-millisecond latency is recorded for regression
diagnosis only and is not representative of a production search service.

## What the errors taught us

1. The query “故宫从哪个门进，从哪个门出” ranks the correct route document second. The source uses
   “入口/离开”, demonstrating the lexical mismatch that dense retrieval or query expansion should
   target.
2. Prefilters improve top-rank metrics, but reduce Recall@10. In a comparison query, filtering for
   “不用预约” removes lower-grade evidence explaining why the alternatives are unsuitable.
3. `weekday`, `season`, `time`, `scope`, and several other constraint keys are not implemented as
   BM25 prefilters. The filtered report counts each unsupported key instead of pretending the
   condition was enforced.
4. Multi-constraint queries are the weakest category: lexical Recall@3 is 0.444. This is the main
   Stage 2 target, not a reason to tune against the 15 pilot questions until they are memorized.

## Engineering boundaries

- Supported filter values are type-checked; invalid values fail explicitly.
- Unsupported filters are surfaced in diagnostics and left to lexical matching.
- Empty/punctuation-only queries return no hits.
- Retrieval results are deduplicated at source-document level before metrics.
- Ties are resolved by document ID for deterministic runs.
- P@k uses `k` as its denominator; recall treats every grade above zero as relevant; NDCG consumes
  grades 1–3; MRR uses the first relevant result.
- Abstention is scored separately because a no-answer query has no valid recall denominator.

## Next experiment

Expand and split the evaluation set, then add one versioned dense embedding adapter. Compare dense
against this exact lexical fingerprint. Only after both single-channel baselines exist should RRF
be evaluated, including dense-down and sparse-down degradation tests.

## Acceptance evidence

On 2026-09-08, `scripts/bootstrap.sh` and `scripts/verify.sh` passed in both the project environment
and a newly created `/private/tmp` virtual environment. Verification covered package and CLI cold
start, the deterministic demo, seed validation, a complete BM25 evaluation run, 28 tests, and Ruff.
The two committed JSON reports contain measured rankings rather than manually copied scores.
