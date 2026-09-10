# Stage 2C: Hybrid retrieval, RRF, and single-channel degradation

## Outcome

Stage 2C adds a graph-compatible `HybridRetriever` that executes BM25 and BGE/Qdrant channels in
parallel, fuses document ranks with RRF, exposes per-channel diagnostics, and degrades to the
surviving channel after an exception or deadline.

This is the first measured hybrid baseline. It deliberately excludes query rewrite and reranking
so that the effect of rank fusion remains identifiable.

## Reproduce

```bash
./scripts/bootstrap.sh --extra dense
travelmind eval-retrieval --root . --retriever hybrid --local-files-only \
  --output evals/results/hybrid_rrf_seed.json
./scripts/verify-dense.sh
```

The default experiment requests ten candidates per channel, uses RRF `k=60`, returns at most ten
documents, and applies a five-second channel deadline. All model/version/artifact metadata from the
dense baseline remains in the report.

## Measured comparison

All runs use the same 15 queries and dataset fingerprint
`a836d2edc0797b00e5ae0123c9167316d8baa1a0abd6211a27391ec211cf83f5`:

| Retriever | P@1 | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR@3 | NDCG@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 lexical | 0.867 | 0.700 | 0.856 | 0.944 | 1.000 | 0.933 | 0.897 |
| BGE-small-zh dense | 0.867 | 0.700 | 0.900 | 0.933 | 0.978 | 0.900 | 0.902 |
| BM25 + BGE RRF | **0.933** | **0.767** | **0.922** | **0.956** | **1.000** | **0.956** | **0.930** |

Hybrid improves Recall@3 by 0.067 over BM25 and 0.022 over dense on this pilot. It also preserves
BM25's Recall@10 while improving first-result and graded-ranking metrics. This is a useful local
signal, not evidence of statistical significance or production quality.

The remaining weakness is multi-constraint retrieval: its Recall@3 is 0.778, below the other query
types. That failure category is a better next optimization target than blindly increasing model
size.

The recorded run had 15 `hybrid` responses, 30 successful channel calls, zero degraded queries,
and zero fallbacks. Failure behavior is therefore established by injected deterministic tests,
not inferred from a healthy benchmark run.

## Runtime contract

```text
                         +-> BM25 ---------+
query -> two-thread fanout                  +-> document-level RRF -> top-k Evidence
                         +-> BGE/Qdrant ----+

one exception/timeout -> surviving ranking + degraded diagnostics
two exceptions/timeouts -> HybridRetrievalError -> graph must not synthesize unsupported facts
```

Each fused hit retains channel rank and raw score, but the public relevance score is RRF. The
response records retrieval mode, channel status/latency/hit count, degraded components, fallback
name, RRF constant, and candidate depth. Third-party exception messages are deliberately omitted.

## Failure-injection evidence

Unit tests cover:

- deterministic RRF ordering and documents found by both channels;
- dense exception with sparse-only fallback;
- one channel timing out while the healthy result survives;
- dual failure raising an explicit error;
- two successful empty responses remaining a valid empty retrieval result;
- graph Evidence identifying its score as RRF;
- filter rejection until both channels share filter semantics;
- no downstream exception text entering diagnostics.

## Limitations and honest interview framing

- Fifteen single-annotator queries are too few for resume-grade generalization claims.
- `k=60` and candidate depth 10 are defaults, not tuned values. Tuning requires a development split.
- Local Qdrant and local ONNX inference do not represent remote p95 latency.
- Thread deadlines do not cancel work already executing inside Python; provider-native timeouts are
  still mandatory.
- There is no confidence threshold or abstention set yet, so a surviving channel is returned based
  on availability, not calibrated quality.
- Hybrid filters, reranking, and query rewrite have not been added.

## Subsequent stage

Stage 2D added a cross-encoder only as an optional layer over the fixed RRF candidate set. It
regressed quality while adding about 90x mean local latency, so RRF remains the default. See
`docs/stage2d-reranker-ablation.md`.

## Acceptance evidence

On 2026-09-08, the installed project passed all 45 tests and Ruff. A newly created environment
without FastEmbed passed the complete normal verification, proving the optional dense dependency
does not leak into BM25 use. A second newly created environment installed the locked `dense` extra,
loaded the model with `--local-files-only`, and passed Dense + Hybrid verification. The final Hybrid
report reproduced the dataset and cached-model fingerprints and recorded no runtime degradation in
the healthy evaluation run.
