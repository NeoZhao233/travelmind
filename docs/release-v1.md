# TravelMind v1 release evidence

## Release position

TravelMind v1 is an interview-grade, evaluation-first agent pilot. Its core value is not a frontend or
the number of model calls; it is an executable chain from retrieval choices through context, planning,
failure handling, and release decisions. Local fixtures and small project-authored datasets limit the
strength of quality claims.

## Golden evidence

| Claim | Evidence | Result |
| --- | --- | --- |
| Hybrid retrieval quality | 15-query seed | Recall@5 0.956, MRR@5 0.956, NDCG@5 0.933 |
| Reranker decision | Fixed Hybrid candidates | Rejected: Recall@5 fell from 0.956 to 0.900 |
| Context pipeline | 7-case real DeepSeek A/B | Task/citation/abstention 1.000; tokens reduced 45.3% |
| Planner selection | 5-case real DeepSeek A/B | Deterministic retained; 4,475 extra tokens, zero lift |
| Frozen release gate | 17 checks | Deterministic passed; paid ranker rejected |
| Judge validity | 21 real calls | v1 rejected: agreement gates failed despite zero fallback |
| Composite outage | 7 synthetic checks | Recoverable completed, unrecoverable failed safely, zero canary leak |
| Durable recovery | 4 independent processes | Resume and receipt replay made zero repeated Planner calls |
| Temporal ingestion | Stage 8 controlled drills | Atomic publish, freshness, quarantine, conflicts, incremental update passed |

These numbers are tied to the committed JSON reports and are pilot evidence, not statistically
significant production benchmarks.

## Deliberately rejected components

- Cross-encoder reranking remains an optional adapter because it regressed retrieval metrics.
- DeepSeek Grader/Rewriter remain unselected because component gates did not pass.
- DeepSeek candidate ranking remains unselected because it added latency/tokens without quality lift.
- LLM-as-Judge v1 remains excluded from release decisions because agreement validity failed.

Negative results are retained because selection quality is part of the project, not an inconvenience
to hide.

## Known boundaries

- Retrieval labels are small and project-authored; independent review is still needed.
- SQLite proves local process durability, not distributed concurrency or PostgreSQL operations.
- The source-fetch drill uses an injected transport rather than live provider outages.
- The incremental fact index is an in-memory reference, not a remote vector-index transaction.
- AI-assisted Judge reference scores are not human ground truth.
- No frontend, production deployment, or remote observability backend is claimed.

## Reproduction

```bash
./scripts/bootstrap.sh --extra dense --extra checkpoint
./scripts/interview-demo.sh
LANGGRAPH_STRICT_MSGPACK=true ./scripts/verify.sh
```
