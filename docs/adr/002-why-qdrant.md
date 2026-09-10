# ADR 002: Use Qdrant for the first hybrid retrieval implementation

## Status

Proposed; acceptance depends on the retrieval benchmark.

## Problem

Travel queries mix fuzzy preferences with exact entity names, dates, prices, and policies. The
retrieval layer needs dense and sparse candidates, metadata filters, rank fusion, and reranking.

## Alternatives

- PostgreSQL with pgvector and full-text search
- Elasticsearch or OpenSearch
- Milvus
- ChromaDB

## Decision

Start with Qdrant because it can host dense and sparse representations and supports hybrid and
multi-stage queries behind one retrieval boundary. Keep PostgreSQL for transactional facts.

## Costs and risks

- Adds another stateful service
- Full-text behavior must be benchmarked against Elasticsearch/BM25
- Small datasets may not justify a dedicated vector database
- Qdrant and PostgreSQL records require stable identifiers and synchronization

## Evidence required

- Recall@k, MRR, and nDCG for dense, sparse, and hybrid variants
- p50/p95 retrieval latency and index size
- Error analysis by exact-keyword and semantic-query subsets

## Interview questions

- Why not put vectors directly in PostgreSQL?
- Why is Elasticsearch not the default?
- How are relational facts synchronized with vector payloads?
- What happens when an attraction changes its opening hours?
