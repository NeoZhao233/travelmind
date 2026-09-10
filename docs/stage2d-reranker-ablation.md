# Stage 2D: Cross-encoder reranker ablation

## Outcome

Stage 2D implements a real, optional BGE cross-encoder after Hybrid RRF, measures it against the
unchanged RRF candidate set, and rejects it as the default path based on observed quality and
latency. Keeping a measured negative result is intentional: the project demonstrates evaluation-
driven architecture rather than accumulating fashionable components.

## Reproduce

The first command may download a registered model of about 1.04GB:

```bash
./scripts/bootstrap.sh --extra dense
travelmind eval-retrieval --root . --retriever reranked \
  --output evals/results/hybrid_bge_reranker_base_seed.json
```

Offline reproduction after provisioning:

```bash
travelmind eval-retrieval --root . --retriever reranked --local-files-only \
  --output evals/results/hybrid_bge_reranker_base_seed.json
./scripts/verify-reranker.sh
```

The report records FastEmbed 0.8.0, model ID, registered license/size/source/model file, and cached
artifact SHA-256 `619302de6ce0b2e8da501e3c62768caf61d43b1a37af65ff5e4789737c556bc8`.

## Quality and latency comparison

Both runs use dataset fingerprint
`a836d2edc0797b00e5ae0123c9167316d8baa1a0abd6211a27391ec211cf83f5` and return ten documents:

| Metric | RRF | RRF + BGE reranker | Delta |
| --- | ---: | ---: | ---: |
| P@1 | 0.933 | 0.933 | 0.000 |
| Recall@1 | 0.767 | 0.722 | -0.044 |
| Recall@3 | 0.922 | 0.878 | -0.044 |
| Recall@5 | 0.956 | 0.900 | -0.056 |
| MRR@3 | 0.956 | 0.933 | -0.022 |
| NDCG@3 | 0.930 | 0.912 | -0.018 |
| Mean in-process latency | 2.56ms | 230.12ms | about 90x |
| p95 in-process latency | 3.23ms | 259.48ms | about 80x |

All 15 reranker calls succeeded, so the regression is not caused by fallback or timeout. Local CPU
latency is not production latency, but the within-machine comparison is sufficient to reject this
model/configuration as the current default.

## Error analysis

- Exact and semantic query groups were unchanged.
- Multi-constraint Recall@3 improved from 0.778 to 0.889. The reranker correctly promoted
  `什刹海` for a low-budget, no-reservation Monday query.
- Metadata Recall@3 fell from 1.000 to 0.667. The most damaging case moved the correct Summer Palace
  ticket document from rank 1 to rank 8 even though it remained in the candidate set.
- This suggests that typed metadata constraints should be enforced structurally rather than hoping
  a general cross-encoder will always preserve them.

The experiment does not establish that all rerankers are harmful. It establishes that this exact
model, input representation, candidate depth, dataset, and CPU runtime do not justify deployment.

## Implemented contract and fallbacks

- A provider protocol keeps unit tests independent of the 1GB model.
- Candidate texts include place name, source title/section, tags, and chunk content.
- Score count and finiteness are validated before reordering.
- Stable ties preserve the pre-rerank order.
- Each hit retains pre-rerank rank/score and the cross-encoder score.
- Runtime exceptions and timeouts preserve base RRF order and add degradation diagnostics.
- Empty candidate sets skip inference cleanly.
- The graph adapter marks cross-encoder scores explicitly.

## Decision and next stage

Default retrieval remains Hybrid RRF. The reranker adapter stays available for later model
comparison after dataset expansion, but is not in the primary runtime.

Stage 2 is now complete at the pilot level. Stage 3 begins Agentic RAG in LangGraph: explicit query
routing, evidence grading, rewrite decisions, bounded retry trajectories, and trajectory-level
evaluation. Before resume-grade claims, the retrieval dataset must still be expanded and split.

## Acceptance evidence

On 2026-09-08, the installed project passed 54 tests and Ruff. A new environment without FastEmbed
passed the complete normal verification. A second new environment installed the locked `dense`
extra, loaded both cached models with network downloads disabled, and passed Dense, Hybrid, and
Reranker verification. The offline report reproduced the dataset fingerprint and reranker artifact
fingerprint, with all 15 reranker calls recorded as successful.
