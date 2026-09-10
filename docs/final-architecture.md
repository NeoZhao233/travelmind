# TravelMind v1 final architecture

## Runtime and data planes

```mermaid
flowchart LR
    U[User request] --> E[CLI / future API]
    E --> G[LangGraph control plane]
    G --> R[Router]
    R --> Q[Bounded query rewrite]
    Q --> H[Hybrid retrieval]
    H --> B[BM25]
    H --> D[Qdrant local dense]
    B --> F[RRF fusion]
    D --> F
    F --> EG[Evidence grader]
    EG --> C[Context engineering]
    C --> P[Deterministic constraint-aware planner]
    P --> V[Typed validator]
    V --> RP[Bounded local repair]
    RP --> O[Itinerary + citations + degradation state]

    DS[DeepSeek Router candidate] -. selected with fallback .-> R
    LR[LLM reranker] -. rejected by ablation .-> F
    LP[DeepSeek planner ranker] -. rejected: no measured lift .-> P

    CP[(Checkpoint)] --- G
    ID[(Idempotency receipts)] --- P
    CB[Timeout / cache / circuit breaker] --- H
    T[Redacted telemetry] --- G

    S[Official sources] --> HF[Conditional HTTPS fetch]
    HF --> RS[(Content-addressed snapshots)]
    RS --> TP[Typed parser]
    TP -->|invalid| X[Quarantine]
    TP --> FC[Fact conflict resolution]
    FC --> II[Incremental fact index]
    II --> BG[Validated versioned build]
    BG -->|atomic promotion| H
```

Solid edges are selected v1 behavior. Dashed edges are evaluated model candidates that remain behind
interfaces or were rejected by measured gates. The local Qdrant, SQLite, and in-memory stores prove
contracts but are not presented as multi-instance production infrastructure.

## LangGraph state flow

```mermaid
flowchart TD
    A[Initialize typed state] --> B{Route}
    B -->|direct retrieval| D[Retrieve]
    B -->|needs rewrite| C[Build / rewrite queries]
    C --> D
    D --> E[Grade evidence]
    E -->|sufficient| F[Build bounded context]
    E -->|insufficient and retry budget remains| C
    E -->|budget exhausted| Z[Safe failure / abstention]
    F --> G[Generate structured itinerary]
    G --> H[Validate hard constraints]
    H -->|valid| J[Complete]
    H -->|repairable| I[Repair affected days only]
    I --> H
    H -->|repair budget exhausted| Z
```

Loop bounds are part of state, so rewrite and repair cannot run indefinitely. Checkpoints persist the
observed state and next node; idempotency receipts separately protect repeatable external operations.

## Selected v1 stack

| Layer | Selected | Why |
| --- | --- | --- |
| Orchestration | LangGraph | Explicit state, branching, bounded loops, checkpoint injection |
| Retrieval | BM25 + BGE-small-zh dense + RRF | Complementary lexical/semantic recall and channel degradation |
| Reranking | None by default | Cross-encoder reduced pilot Recall/MRR/NDCG and added latency |
| Agent policies | DeepSeek Router; deterministic Grader/Rewriter fallback | Only Router passed component gates |
| Context | 768-token refined coverage pipeline | Smallest passing budget; deterministic provenance-preserving refinement |
| Planning | Deterministic explainable greedy + bounded repair | DeepSeek ranking added cost with zero measured quality lift |
| Evaluation | Exact metrics + frozen gates; Judge v1 rejected | Judge agreement failed; hard constraints remain deterministic |
| Persistence | In-memory tests, SQLite local proof, PostgreSQL target | Honest separation of test/local/production workload classes |
| Ingestion | Conditional fetch + immutable snapshots + typed incremental index | Freshness, reproducibility, quarantine, atomic promotion |

## Trust boundaries

- LLM output, retrieved text, HTTP responses, and parser output are untrusted inputs.
- Hard constraints, freshness admission, schema checks, retry budgets, and release gates are code.
- A fallback completion is observable degradation, not a healthy request.
- Missing admissible evidence produces abstention or failure, never an unsupported itinerary.
- Exact-once is not claimed; checkpoint recovery and idempotency receipts address different risks.
