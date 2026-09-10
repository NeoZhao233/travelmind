# Stage 1: evidence and evaluation data foundation

## Outcome

Stage 1 turns a set of travel facts into a versioned, validated retrieval corpus and a small
human-reviewed evaluation set. It deliberately stops before embeddings and search engines so that
later retrieval experiments all use the same input records and labels.

The current seed set contains:

- 5 Beijing places;
- 14 source-document sections;
- 22 typed facts;
- 14 deterministic chunks at the current 500-character setting;
- 15 reviewed retrieval queries, evenly split across semantic, exact, metadata, temporal, and
  multi-constraint categories.

These are corpus statistics, not retrieval-quality metrics. Recall, MRR, NDCG, latency, and cost
will only be reported after a retriever is implemented and the evaluation command can reproduce
them.

## Data flow

```text
official or government page
  -> manually reviewed, paraphrased source section
  -> Pydantic schema validation
  -> normalization and structure-aware chunking
  -> stable content-derived chunk ID
  -> future sparse/vector indexes

human query and document relevance labels
  -> schema and referential-integrity validation
  -> future retrieval evaluation runner
```

## Contracts

`PlaceRecord` stores stable entity metadata. `SourceDocument` stores a citable source section plus
authority and freshness metadata. `FactRecord` extracts values that must support filtering or
deterministic checks. `RetrievalExample` stores document-level graded relevance, expected places,
hard filters, and expected fact types.

The validation command fails before indexing when it finds:

- malformed JSONL with a file and line number;
- duplicate entity, document, fact, or query IDs;
- a document, fact, or label referencing a missing record;
- a fact whose place disagrees with its source document;
- an evaluation query requesting a fact type absent from its expected places;
- naive collection timestamps without a timezone;
- duplicate content-derived chunk IDs.

Run it with:

```bash
travelmind validate-data --root .
```

## Deliberate limitations

- The seed content is a manually curated paraphrase, not a production crawler or immutable HTML
  archive.
- Fifteen queries are enough to exercise the pipeline, not enough to establish statistical
  significance or broad coverage.
- One project-owner annotator reviewed the initial labels. A second annotator and disagreement
  protocol are required before trustworthy benchmark claims.
- Chunking uses a reproducible character limit. `token_estimate` is only a rough budget estimate,
  not output from the embedding model's tokenizer.
- No source refresh scheduler, conflict resolver, vector index, BM25 index, or retrieval metric is
  implemented yet.

## Acceptance evidence

- `tests/test_domain_models.py` covers schema invariants.
- `tests/test_chunking.py` covers normalization, bounds, and stable IDs.
- `tests/test_dataset.py` checks the complete seed set and line-aware failure reporting.
- `scripts/verify.sh` includes data validation alongside import, CLI, unit-test, and lint checks.

On 2026-09-08, the full bootstrap and verification sequence passed both in the project environment
and in a newly created `/private/tmp` virtual environment: the package cold-started from
`site-packages`, all 15 tests passed, Ruff passed, the demo completed, and the data counts above
were reproduced. The temporary environment verifies installation isolation; it is not part of the
project deliverable.

## Next stage

Stage 2 will build a measurable retrieval baseline: lexical search, dense search, RRF fusion,
metadata filtering, optional reranking, and an evaluation runner. Each addition must be compared
against direct retrieval on this fixed dataset before it is kept.
