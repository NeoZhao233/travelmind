# Stage 3A: Agentic RAG control plane

## Outcome

Stage 3A replaces the Stage 0 count-only retrieval loop with a structured LangGraph control plane:

```text
initialize -> route_query -> retrieve -> grade_evidence
                                      | sufficient -> generate -> validate
                                      | insufficient and budget remains
                                      +-> rewrite_query -> retrieve
                                      | exhausted
                                      +-> explicit fallback
```

The default policies are deterministic baselines. LLM policies are not yet claimed.

## Implemented contracts

- `RoutingDecision`: intent, retrieval strategy, structured-validation need, decomposition flag, and
  reason codes.
- `EvidenceAssessment`: required, covered, and missing aspects plus sufficiency and coverage score.
- `TrajectoryEvent`: node, attempt, outcome, reason codes, and sanitized exception type.
- Injected `QueryRouter`, `EvidenceGrader`, and `QueryRewriter` protocols.
- LangGraph state containing attempts, queries, evidence, assessment, trajectory, degradations, and
  dependency failures.
- `MultiQueryRRFAdapter` with independent execution, deduplication, four-query maximum fanout,
  partial failure, and RRF fusion.

## Current evidence grading baseline

The grader identifies explicitly requested travel-fact aspects: admission, opening hours, booking,
route/transport, and accessibility. It requires at least one official, structured, or realtime
source and complete lexical coverage of requested aspects. Missing aspects become targeted rewrite
terms.

This is stricter than “at least one result,” but it remains a lexical heuristic that can have false
positives and false negatives.

## Engineering fallbacks

| Failure | Behavior |
| --- | --- |
| Router exception | Deterministic Hybrid decision; mark `query_router` degraded |
| Grader exception | Deterministic trusted-source and coverage grader |
| Rewriter exception or empty output | Deterministic missing-aspect expansion |
| First retrieval timeout | Record type, grade current evidence, rewrite, retry within budget |
| Partial multi-query failure | Fuse surviving rankings and expose failed-query count |
| All query variants fail | Explicit retrieval error; graph eventually terminates |
| Evidence remains incomplete | Return failure with missing aspects; do not generate |

Provider exception messages are excluded from state. This protects credentials and request data and
keeps checkpoint state compact.

## What is not complete

- The Router currently always selects measured Hybrid RRF; its intent classification is a rule
  baseline, not a learned accuracy claim.
- The decomposition flag is recorded, while extra queries are produced after the grader identifies
  missing aspects.
- There is no production LLM policy adapter or structured-output repair yet.
- There is no held-out trajectory dataset, rewrite-recovery metric, token/cost accounting, or
  calibrated sufficiency threshold yet.
- The CLI demonstration uses deterministic evidence and is not an end-to-end quality benchmark.

## Reproduce

```bash
./scripts/bootstrap.sh
travelmind agentic-demo "周一带父母去故宫，需要门票和预约信息"
./scripts/verify.sh
```

## Next stage

Stage 3B will create an independently labeled routing and trajectory dataset before evaluating an
LLM router, grader, or rewriter. The test split must remain untouched during prompt development.
Metrics will include route accuracy, sufficiency precision/recall, rewrite recovery, average
retrieval calls, fallback rate, latency, and token cost.

## Acceptance evidence

On 2026-09-08, the installed project passed 69 tests and Ruff. The deterministic Agentic CLI
completed with structured routing, sufficiency, and six-node trajectory output. A newly created
environment without FastEmbed passed package import, both CLI demos, data validation, BM25
evaluation, all tests, and linting. Failure-injection tests cover Router, Grader, Rewriter,
Retriever, and partial/all Multi-Query failures.
