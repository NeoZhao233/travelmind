# ADR 006: In-process BM25 with deterministic Chinese character n-grams

## Status

Accepted as the Stage 2 lexical baseline, not as the final production search engine.

## Problem

Hybrid retrieval needs an independently measurable sparse channel. Choosing a hosted search engine
or a learned tokenizer first would mix retrieval behavior with infrastructure, dictionary versions,
and service configuration before metric contracts have been verified.

## Decision

Implement the standard positive-IDF BM25 formula in process with `k1=1.5` and `b=0.75`. Normalize
text with NFKC and lowercase; retain ASCII alphanumeric terms; emit Chinese unigrams and adjacent
bigrams. Index place name/location/categories plus document title/section/tags/content. Aggregate
multi-chunk results by each source document's maximum chunk score.

Parameters are conventional starting values, not tuned optima. They must be tuned only on a future
development split and evaluated once on a held-out split.

## Alternatives considered

- **TF-IDF.** Simpler, but lacks BM25's term-frequency saturation and document-length normalization.
- **Jieba or another dictionary segmenter.** More linguistic tokens, but introduces dictionary
  versioning and poor handling of unseen place names. It remains an ablation candidate.
- **Elasticsearch/OpenSearch BM25.** Production-capable analyzers and scaling, but heavy for a
  14-document metric-contract baseline and adds service failure variables.
- **Qdrant sparse vectors.** Attractive for one-store hybrid retrieval, but the baseline should
  first prove sparse scoring independently of storage and network configuration.
- **LLM query expansion before BM25.** May bridge paraphrases but adds model cost and makes the first
  baseline nondeterministic.

## Consequences

- The baseline is offline, explainable, fast, and API-key free.
- Character bigrams handle place names without a dictionary but increase index terms and do not
  solve synonyms such as “进” versus “入口”.
- Indexing metadata as text improves lexical matching but can overemphasize repeated place names.
- Maximum chunk aggregation favors a document with one strong passage; other aggregation rules need
  separate evaluation on multi-chunk documents.
- A later production adapter can replace this implementation while retaining the same evaluator.

## Filter decision

City, district, category, admission ceiling, booking requirement, and accessibility can be applied
from Stage 1 records. Other keys are reported as unsupported. Both unfiltered and prefiltered
experiments are retained because early hard filtering can remove contradictory evidence needed to
explain why an option was rejected.

## Interview prompts

- Explain the roles of IDF, `k1`, `b`, term-frequency saturation, and length normalization.
- Why do Chinese text and unseen place names complicate word segmentation?
- Why use both unigrams and bigrams, and what are their costs?
- Why should BM25 and dense retrieval be evaluated independently before RRF?
- Why did prefiltering improve P@1/NDCG but hurt Recall@10?
- When should a constraint be a retrieval filter versus a post-retrieval validator?
