# Stage 3C.2: live Hybrid RRF trajectory comparison

## Outcome

The frozen `rule-v1` Agentic control plane and one-shot Direct control were run over the same local
BM25 + BGE-small-zh-v1.5 + RRF stack at top 3 on all 15 retrieval seed queries.

| Metric | Direct | Agentic |
| --- | ---: | ---: |
| Supported completion rate | 0.933 | 0.933 |
| Unsupported generation rate | 0.000 | 0.000 |
| Abstention rate | 0.067 | 0.067 |
| Mean Hybrid rank calls | 1.000 | 1.133 |
| Mean latency | 2.74 ms | 3.83 ms |
| p95 latency | 4.50 ms | 9.59 ms |

Unlike the controlled recovery experiment, Agentic RAG produced no quality lift. Only
`beijing-multi-001` triggered a rewrite: the first pass lacked accessibility evidence, and the
targeted second pass still could not retrieve evidence absent from the seed knowledge base. The
request safely failed after two attempts.

Agentic control increased mean rank calls by 13.3%, mean latency by about 39.8%, and p95 latency by
about 113%. These local timings exclude index/model construction and do not predict remote latency.

## Why this does not contradict Stage 3C

The controlled dataset deliberately contains three recoverable second-step cases and proves the
control plane can recover them. The live seed has a strong first-pass Hybrid baseline and its only
detected gap is not recoverable from the corpus. One experiment tests mechanism capability; the
other tests opportunity frequency in the current data distribution.

## Oracle contract

A completion is supported only when retrieved documents intersect labeled relevant documents and
jointly cover every expected fact type. This is stricter than trusting the deterministic Grader's
binary output. Full document IDs, traces, calls, and timings are stored per query.

## Limits

- The 15-query set has no Agentic-specific held-out split.
- The deterministic planner is not an answer-quality evaluation.
- Local in-process latency is useful only for same-machine A/B comparison.
- A larger corpus with hard negatives and known recoverable gaps is needed before optimization.

## Reproduce

```bash
./scripts/bootstrap.sh --extra dense
travelmind eval-live-agentic \
  --root . \
  --limit 3 \
  --local-files-only \
  --output evals/results/live_hybrid_agentic_rule_v1_seed.json
```
