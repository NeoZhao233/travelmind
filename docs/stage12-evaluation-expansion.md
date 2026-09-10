# Stage 12: evaluation-set expansion and re-test

## Why this stage exists

The previous `15` retrieval queries and `4` runtime trajectories were useful regression seeds but
were too small for strong resume claims. Stage 12 expands coverage while explicitly avoiding a fake
sample-size claim: three paraphrases of one intent share an `intent_id`, stay in one split, and count
as one effective intent cluster for uncertainty estimates.

## Retrieval benchmark v2

`retrieval_benchmark_v2.jsonl` contains:

- 105 queries grouped into 35 intent clusters;
- 21 queries for each of semantic, exact, metadata, temporal, and multi-constraint retrieval;
- 75 answerable queries and 30 out-of-corpus/no-answer queries;
- 45 development and 60 test queries, split at intent-cluster level;
- three explicitly authored paraphrases per intent;
- zero human-reviewed labels—the entire dataset remains a Codex-authored draft.

The generator is committed so the expansion is inspectable rather than an opaque generated file.
Validation rejects duplicate query text, duplicate IDs, incomplete paraphrase groups, and an intent
appearing in both development and test.

## Retrieval re-test

Metrics below are over all 75 answerable queries unless noted otherwise.

| Variant | Recall@5 | MRR@5 | NDCG@5 | Mean local latency |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 0.962 | 0.977 | 0.962 | 0.04 ms |
| BGE dense | 0.956 | 0.931 | 0.922 | 2.13 ms |
| Hybrid RRF | **0.971** | **0.957** | **0.953** | 2.82 ms |
| Hybrid + Cross-Encoder | 0.958 | 0.947 | 0.949 | 216.30 ms |

The reranker again reduces Recall@5 and MRR@5 while increasing mean local latency by roughly 77x.
This strengthens the prior rejection direction, but it is still not independently reviewed evidence.

For Hybrid RRF, the intent-cluster bootstrap estimate for Recall@5 is `0.971` with a deterministic
95% interval of `[0.920, 1.000]`. This interval treats 35 intent groups—not 105 paraphrases—as the
effective units. The held-out test subset reaches Recall@5 `1.000`, but that number must not be placed
on a resume until the labels receive independent review.

## The abstention failure the larger set exposed

All rankers return a ranked document for every no-answer query, so their raw abstention accuracy is
`0.000`. High Recall therefore does not prove the system knows when the corpus cannot answer. RRF's
rank-based score is especially unsuitable as a confidence value because unrelated and relevant top
scores overlap.

An experimental lexical admission gate selects one BM25 top-score threshold on development data only
and evaluates it once on test data. Compared with an always-admit baseline (balanced accuracy `0.500`),
the frozen test result is:

| Metric | Query level (60 test queries) | Intent level (20 clusters) |
| --- | ---: | ---: |
| Answerable recall | 0.956 | 1.000 |
| No-answer abstention accuracy | 0.800 | 0.800 |
| Balanced accuracy | 0.878 | 0.900 |

The quality gates pass, but the component remains `blocked_pending_human_review`. A corpus-specific
lexical threshold also needs recalibration after indexing changes and cannot replace semantic
entailment or the downstream Evidence Grader.

## Runtime failure matrix v2

The runtime dataset grows from 4 trajectories to 34 distinct cases across:

- candidate search, availability, booking, and travel-time tools;
- timeout, connection, permission, runtime exception, invalid output, and insufficient evidence;
- successful same-step retry, exhausted retry followed by replan, fallback-path transient recovery,
  fallback-path permanent failure, and safe stop.

All 34 exact status/replan/tool-call/final-place contracts pass. Among matrix cases that require a
strategy change, the no-replan baseline recovers `0.000` and the Agentic Runtime recovers `1.000`;
single transient retry, completed-observation reuse, and unrecoverable safe stop are each `1.000`.
These are deterministic fault-injection contracts, not estimates of production incident recovery.

## Decision

- Keep Hybrid RRF as the ranking default and Cross-Encoder disabled.
- Do not claim raw Retriever abstention capability.
- Keep the lexical admission candidate behind a review gate.
- Replace the four-case Runtime resume wording with 34-case fault-matrix coverage, while retaining
  the fixture/tool limitation.
- Ask a human reviewer to validate the v2 labels before promoting any new quality number into the
  release manifest or resume.

The reviewer-facing checklist is `evals/annotations/retrieval_benchmark_v2_review.md`. It contains
35 decisions rather than 105 repeated decisions because each item groups three paraphrases.
