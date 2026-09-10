# TravelMind architecture

## Objective

Build an evidence-grounded travel planner whose retrieval, agent trajectory, constraints, cost,
and latency can be evaluated independently.

## Runtime flow

```text
request
  -> parse and normalize constraints
  -> plan retrieval queries
  -> dense + sparse + structured retrieval
  -> fuse and rerank candidates
  -> grade evidence; rewrite and retry when needed
  -> construct a token-budgeted context
  -> generate a structured itinerary
  -> validate deterministic constraints
  -> repair only invalid portions
  -> verify evidence coverage
```

## Design boundaries

- LangGraph owns control flow and bounded loops, not business data.
- Qdrant owns semantic and lexical retrieval, not transactional records.
- PostgreSQL owns normalized place facts, user preferences, and experiment metadata.
- Deterministic code owns arithmetic, overlap checks, and hard constraints.
- LLMs own ambiguous language understanding, query planning, evidence judgment, and synthesis.
- Every provider is hidden behind a small interface so experiments can swap implementations.

## Stage 1 data boundaries

```text
PlaceRecord 1 ---- * SourceDocument 1 ---- * FactRecord
                           |
                           +---- * deterministic Chunk

RetrievalExample ---- graded relevant SourceDocument IDs
                 +---- expected Place IDs / fact types / hard filters
```

- Places are stable entities; volatile values do not belong in the place record.
- Source documents retain citable explanatory text plus authority and freshness metadata.
- Facts duplicate selected source claims in typed form when filters or hard constraints need them.
- Chunks are derived index artifacts and can change during experiments.
- Retrieval labels target source documents so chunking can be ablated without relabeling the set.
- Ingestion validation fails before indexing on malformed schemas, duplicates, broken references,
  missing expected fact coverage, or timezone-ambiguous observations.

## Evaluation-first rule

No advanced component is accepted because it sounds useful. Lexical and dense retrieval are the
independent baselines.
Hybrid fusion, reranking, query rewriting, self-correction, memory, and context compression are
added one at a time and kept only when a fixed evaluation set demonstrates an acceptable
quality/latency/cost trade-off.

The Stage 1 pilot set validates evaluation plumbing but is too small and too narrowly annotated to
support general quality claims. Stage 2 must report a lexical or dense baseline before hybrid
retrieval is presented as an improvement.

## Stage 2A retrieval baseline

The current sparse path is an in-process BM25 implementation over deterministic Chinese character
unigrams/bigrams and ASCII terms. It returns chunk evidence to the graph but evaluates rankings at
source-document level. The evaluator is independent of BM25 so dense, fused, and reranked adapters
can reuse identical metric definitions and labels.

Metadata filtering is an explicit experiment mode rather than an unconditional step. This matters
for comparison questions: a strict filter may find the final candidate faster while deleting
evidence that explains why other candidates fail the user's constraints.

## Stage 2B dense baseline

The dense path injects an `EmbeddingProvider` into `QdrantDenseRetriever`. Production code uses the
version-recorded FastEmbed/BGE adapter; unit tests use deterministic fake vectors. Documents and
queries are validated for count, dimension, finite values, and nonzero content before Qdrant sees
them.

```text
shared searchable chunk text
  -> BGE document embedding
  -> deterministic UUIDv5 point + provenance payload
  -> Qdrant cosine collection

query + Chinese retrieval instruction
  -> BGE query embedding
  -> Qdrant top chunks
  -> max-score aggregation by source document
  -> shared evaluator or graph Evidence
```

Qdrant local memory mode validates the collection and payload contract, not production networking,
distributed durability, or HNSW behavior. Sparse and dense raw scores remain isolated.

## Stage 2C hybrid baseline

`HybridRetriever` fans out to BM25 and dense retrieval concurrently and applies document-level RRF.
It exposes channel ranks/raw scores for diagnosis while using only ranks for fusion. Single-channel
exceptions and timeouts return an explicitly degraded result; dual failure raises an error.

```text
BM25 ---- rank list --+
                      +-- RRF(k=60) --> fused Evidence
Dense --- rank list --+
```

The evaluator aggregates retrieval modes, channel statuses, degraded component counts, and fallback
counts. Metadata filters are rejected in hybrid mode until both channels enforce the same contract.

## Stage 2D reranker ablation

An optional `RerankingRetriever` wraps the fixed Hybrid RRF candidates. Its injected provider scores
query-document pairs, validates one finite score per candidate, and preserves RRF order after an
exception or timeout.

The real BGE reranker reduced quality and increased mean local latency by about 90x, so it is not in
the default runtime. This is an architectural decision backed by an ablation, not a missing feature.
The adapter remains available for future model comparisons after the dataset gains a proper
development/held-out split.

## Stage 3A Agentic RAG control plane

The Agentic graph separates routing, retrieval, evidence grading, rewrite, generation, and
validation. Every decision is a compact Pydantic object; trajectories store reason codes rather than
free-form model reasoning. Missing fact aspects drive bounded rewrites, which execute independently
and fuse through Multi-Query RRF.

All policy boundaries are injectable. Deterministic policies are both the first baseline and the
fallback for future LLM policy failures. The current router retains Hybrid RRF as the only selected
backend because Stage 2 measured it as the strongest default; adding choices without evaluation
would create decorative routing rather than useful agent behavior.

## Stage 4A/4B context construction and budgeting

Context is assembled as typed items before it is rendered. System instructions, the current user
request, and explicit hard constraints are mandatory; retrieved evidence is optional and carries
priority plus provenance metadata. The baseline builder admits every item so the budgeted path can
be measured against the same inputs.

```text
typed ContextItem list
  -> unbounded baseline + privacy-safe trace
  -> reserve output tokens and safety margin
  -> admit all mandatory items or fail closed
  -> cap each evidence item
  -> stable priority packing with clip/drop decisions
  -> PackedContext + privacy-safe ContextTrace
```

`ContextTrace` records item IDs, kinds, token estimates, provenance, and admission decisions, but
never raw prompt or evidence content. This keeps traces useful for debugging while reducing the
risk of logging personal travel details. A tokenizer adapter may fall back to the conservative
heuristic estimator and marks the trace as degraded; mandatory-item overflow raises a typed error
instead of silently truncating user constraints.

The final pilot sweep selected a 768-token envelope with 192 tokens reserved for output and a 64-token
safety margin. It is the smallest tested configuration that preserved every mandatory item and
reached at least 0.9 mean relevant-document recall.

## Stage 4C coverage-aware packing

The coverage selector derives requested fact aspects from the query and hard filters, while
candidate aspects come from typed facts created during ingestion. It adds a bounded marginal
coverage bonus to retrieval priority and then reuses the same deterministic budget packer.

```text
query + hard filters -> requested aspects
typed facts          -> candidate aspects
                              |
retrieval priority + bounded new-aspect bonus
                              |
                 Stage 4B cap/clip/drop
```

Evaluation labels are outside the selection path. Missing aspect signals reduce every bonus to zero,
which recreates retrieval order. The 768 A/B improves aspect and multi-constraint recall while
keeping token use unchanged.

## Stage 4D evidence refinement

The context pipeline refines evidence before coverage selection and token packing. Near-duplicate
matching is guarded by structured fact values so numerically conflicting claims cannot be merged.
Conflict resolution uses authority first and same-authority observation time second; ties remain
explicitly unresolved. Extractive compression scores whole source sentences and preserves original
text spans plus document provenance.

```text
evidence -> value-aware dedup -> conflict policy -> extractive compression
         -> coverage selection -> deterministic token packing
```

Every refinement decision is deterministic and provider-independent. An LLM compressor or semantic
deduplicator can be added only as an evaluated candidate with this path as its outage fallback.

## Stage 4E memory boundaries

Execution recovery, short-term conversation history, and long-term preferences are separate stores
and schemas. Short-term keys contain tenant, user, and thread identity; preferences omit thread but
retain tenant and user. Memory is rendered as optional `HISTORY` context, so it cannot displace the
current request or explicit constraints.

```text
LangGraph checkpoint -> execution recovery only
tenant/user/thread   -> TTL + bounded recent turns
tenant/user          -> consented typed preferences
                         |
current request overrides memory -> optional HISTORY -> token packer
```

The reference store is in process and deterministic. The protocol boundary permits Redis for
short-term TTL data and PostgreSQL for durable preferences without changing privacy semantics.

## Stage 4F selected context pipeline

The pilot default is the 768-token refined-coverage pipeline. Only document IDs and model-useful
source metadata are rendered; URLs and internal selection metadata remain outside the prompt. A real
DeepSeek A/B selected this path over unbounded context through combined task-success, citation,
abstention, fallback, token, and latency evidence. Unbounded context remains an evaluation control,
not the runtime default.

## Stage 5A hard-constraint boundary

The model proposes a typed itinerary; it does not certify feasibility. A standalone deterministic
validator recomputes cost and checks requested days, required/excluded places, time overlap,
evidence, availability freshness/status, opening-window containment, and booking confirmation.

```text
LLM or deterministic candidate planner
                 |
          typed Itinerary
                 |
request constraints + sourced availability -> deterministic validator
                 |
      valid plan OR typed violations
```

Operational facts use timezone-aware half-open intervals and are unique by place and service date.
Missing or stale facts fail closed for the affected activity. Stage 5C will consume the same typed
violations for bounded local repair, keeping repair policy separate from validation truth.

## Stage 5B explainable candidate construction

The deterministic candidate planner performs feasibility filtering before scoring. It uses sourced
directed travel edges and daily origin windows, then sends the completed plan back through Stage
5A's independent validator.

```text
candidates + constraints + availability + directed travel matrix
                              |
          feasible slot + return-path filtering
                              |
 required bonus + relevance + interests - travel - cost
                              |
        selected itinerary + per-candidate decision trace
                              |
              independent hard validation
```

The baseline is deliberately greedy and provider-independent. CP-SAT, search, or LLM candidates can
replace the generation strategy only after outperforming it under the same validation and
evaluation contracts.

## Stage 5C bounded local repair

Typed violations route into a separate LangGraph loop. Arithmetic and activity removals use smaller
actions; operational and travel failures replan only tagged days. Unsupported violations bypass
repair, while every candidate returns to the same deterministic validator.

```text
Itinerary -> validate -> valid -> complete
                 |
          typed violations
                 |
    repairable? --no--> safe failure
         |
  bounded local repair
         |
      revalidate --attempts exhausted--> safe failure
```

The repairer is injected so an LLM or solver can be evaluated later. The deterministic day repairer
is both the baseline and provider-outage fallback.

## Stage 5D end-to-end context and selection

The runtime separates bounded narrative evidence from provenance-linked structured candidates. The
selected planner remains deterministic after a real DeepSeek shortlist A/B produced no quality
lift. DeepSeek can influence soft ordering only; scheduling, arithmetic, travel, and validation stay
provider-independent.

```text
Hybrid RRF -> retrieved evidence --raw text--> refined 768-token prompt
                     |
                     +--typed place/provenance--> candidate plane
                                                       |
                              deterministic or LLM soft ranking
                                                       |
                              deterministic scheduling/validation/repair
```
