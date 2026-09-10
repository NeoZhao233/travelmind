# ADR 009: Keep the BGE cross-encoder out of the default retrieval path

## Status

Rejected as the default Stage 2 retrieval path; retained as an optional experiment adapter.

## Problem

RRF uses only rank positions and cannot model query-document interactions token by token. A
cross-encoder may improve top-result ordering, but it adds model weight, inference latency, another
failure domain, and can still regress project-specific query types.

## Experiment decision

Evaluate `BAAI/bge-reranker-base` only after the fixed BM25 + BGE RRF candidate stage. FastEmbed
registers it as an approximately 1.04GB, MIT-licensed BGE cross-encoder. Score at most ten candidates
and retain the RRF order on reranker error, invalid output, or timeout.

The measured model is **not enabled by default** because it reduced every primary quality metric
except P@1, which stayed flat, while adding roughly 90x mean in-process latency.

## Why this model was tested

- It supports Chinese rather than being an English MS MARCO-only reranker.
- Its MIT license avoids the non-commercial restriction of the registered Jina multilingual
  alternative.
- It is available in the already pinned FastEmbed runtime, so the serving path remains ONNX-based
  and no PyTorch stack is introduced.
- It provides a meaningful stronger-model experiment instead of selecting a tiny English model
  merely for fast numbers.

## Alternatives considered

- **English MiniLM cross-encoders.** About 80–120MB and faster, but the language/domain mismatch
  makes them a poor Chinese baseline.
- **Jina multilingual reranker.** Multilingual but the registered model is about 1.11GB with a
  CC-BY-NC license, which is a poor default for a potentially commercial internship project.
- **Hosted reranking API.** Avoids local 1GB deployment but introduces network latency, recurring
  cost, privacy concerns, provider drift, and an external outage path.
- **LLM-as-reranker.** Flexible but slower, more expensive, less deterministic, and harder to
  evaluate at this stage.
- **Learned project-specific fusion/reranking.** Requires a much larger train/development/test set;
  fitting it to 15 queries would be leakage, not optimization.
- **No reranker.** Selected as the current default because RRF is both better and much faster on the
  fixed pilot.

## Measured evidence

Same dataset fingerprint for both rows:

| Path | P@1 | Recall@3 | MRR@3 | NDCG@3 | Mean latency | p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| RRF | 0.933 | 0.922 | 0.956 | 0.930 | 2.56ms | 3.23ms |
| RRF + cross-encoder | 0.933 | 0.878 | 0.933 | 0.912 | 230.12ms | 259.48ms |

The reranker improved multi-constraint Recall@3 from 0.778 to 0.889 but reduced metadata Recall@3
from 1.000 to 0.667. For `海淀区的皇家园林景点门票信息`, it moved the grade-3 ticket document from
rank 1 to rank 8. This is an error-analysis result, not proof that the model is generally weak.

## Failure policy

- Runtime exception, invalid score count, NaN/infinity, or timeout preserves the RRF order.
- Diagnostics record status and exception type but never third-party exception text.
- Startup/model-provisioning failure aborts the reranked experiment explicitly; it must not write a
  report falsely labeled as a successful reranker run.
- A thread deadline cannot terminate already-running inference. Production needs process isolation
  or provider-native cancellation plus bounded concurrency.
- Fallback activation is an alert signal, not a quality-equivalent success.

## What would change the decision

Expand and independently review the dataset, add a development/held-out split, then test another
Chinese/multilingual model or domain adaptation. Adoption requires a prespecified quality gain and
latency budget, not a favorable anecdote.

The full failure analysis, input-representation ablation, evidence-coverage explanation, and oracle
leakage warning are recorded in `docs/reranker-regression-analysis.md`.
