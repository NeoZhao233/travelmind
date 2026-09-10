# Stage 2B: Chinese dense retrieval baseline

## Outcome

Stage 2B adds a real Chinese embedding model, an injected embedding-provider contract, a Qdrant
dense index, document-level aggregation, and a dense run through the same evaluator and dataset
fingerprint as BM25.

The selected baseline is `BAAI/bge-small-zh-v1.5`, executed by FastEmbed 0.8.0 with 512-dimensional
vectors and cosine similarity. The query receives the model author's recommended Chinese retrieval
instruction; passages do not. Qdrant runs in local memory mode for this experiment.

## Reproduce

First provision the optional runtime and download the model:

```bash
./scripts/bootstrap.sh --extra dense
travelmind eval-retrieval --root . --retriever dense \
  --output evals/results/dense_bge_small_zh_v15_seed.json
```

After the model is cached, prove that inference works without a model download:

```bash
travelmind eval-retrieval --root . --retriever dense --local-files-only \
  --output evals/results/dense_bge_small_zh_v15_seed.json
./scripts/verify-dense.sh
```

The cache lives under `.cache/fastembed` and is excluded from version control. The report records
the model name, FastEmbed version, dimension, query instruction, registered artifact sources, model
filename, and a SHA-256 fingerprint over the cached model directory.

## Measured comparison

Both rows below use dataset fingerprint
`a836d2edc0797b00e5ae0123c9167316d8baa1a0abd6211a27391ec211cf83f5`:

| Retriever | P@1 | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR@3 | NDCG@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 lexical | 0.867 | 0.700 | 0.856 | 0.944 | 1.000 | 0.933 | 0.897 |
| BGE-small-zh dense | 0.867 | 0.700 | 0.900 | 0.933 | 0.978 | 0.900 | 0.902 |

Dense retrieval improves Recall@3 by 0.044 on this pilot, but lowers Recall@5/10 and MRR@3. It is
complementary, not uniformly superior.

The query-type breakdown is more informative:

- exact Recall@1 rises from 0.667 to 1.000, including the “进/入口、出/离开” route case;
- multi-constraint Recall@3 rises from 0.444 to 0.667;
- semantic Recall@1 falls from 0.833 to 0.500 even though semantic Recall@3 remains 1.000;
- temporal Recall@3 remains 0.833.

These results motivate rank fusion, while also showing that the 15-query seed is too small for model
selection. No statistical significance or production-quality claim is made.

## Engineering safeguards

- Unit tests inject a deterministic fake embedder; normal tests never download a model.
- Document and query vectors must have the declared dimension, contain only finite values, and not
  be all-zero.
- Chunk IDs become deterministic UUIDv5 Qdrant point IDs, making repeated indexing idempotent.
- Missing point payload identity fails the query instead of returning uncitable evidence.
- Empty or punctuation-only queries return no results.
- Unsupported dense filters are reported; the CLI refuses `--apply-filters` in Stage 2B.
- Embedding/index failures and query-time failures have distinct exception types for the later
  hybrid fallback policy.
- Raw cosine scores may be negative and are kept as raw scores. They must not be added to BM25
  scores directly.

## Failure observed during development

The first FastEmbed attempt tried to write Hugging Face/Xet logs under the user cache, which the
sandbox denied. FastEmbed fell back to its registered archive source and completed. The adapter now
points Hugging Face and Xet caches to the project-local ignored cache while preserving explicit
user overrides. A second run with `--local-files-only` succeeded.

## Limitations

- Qdrant local mode does not represent network latency, distributed failure, or production HNSW
  tuning.
- The remote model registry entry is external; the experiment mitigates drift by recording a local
  artifact fingerprint after provisioning.
- There is no calibrated similarity threshold or abstention benchmark yet.
- Dense metadata filtering and automatic sparse fallback are not wired in Stage 2B.
- The graph-compatible adapter exists, but the CLI demo still uses deterministic test adapters.

## Subsequent stage

Stage 2C now queries BM25 and dense channels independently, fuses document ranks with RRF, records
channel contribution, and degrades to the surviving channel on a single-channel failure. See
`docs/stage2c-hybrid-rrf.md` for its measured comparison and limitations.

## Acceptance evidence

On 2026-09-08, the normal package path passed 38 tests and Ruff. A new virtual environment without
the `dense` extra passed the complete normal verification, proving sparse use does not depend on
FastEmbed. A second new environment installed `dense`, loaded the cached model with network access
forbidden, rebuilt the Qdrant collection, reproduced Recall@3 0.900, and reproduced cached artifact
fingerprint `236d8e4fd3136df960f15b6d678578513c280dd9b4626ffc0b45c9594ccf419a`.
