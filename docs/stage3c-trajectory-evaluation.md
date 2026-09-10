# Stage 3C: controlled trajectory evaluation

## Outcome

Seven scripted retrieval trajectories compare one-shot Direct RAG with the bounded Agentic RAG
control plane. Each step returns allowlisted real corpus document IDs or an injected timeout. This
isolates orchestration behavior from ranker variance and does not claim end-to-end Hybrid RRF lift.

| Metric | Direct | Agentic |
| --- | ---: | ---: |
| Task success rate | 0.429 | 0.857 |
| Unsupported generation rate | 0.143 | 0.143 |
| Safe abstention rate | 0.571 | 0.143 |
| Average retrieval calls | 1.000 | 1.571 |
| Rewrite recovery rate | not applicable | 1.000 |

Agentic control recovered all three cases where the first step was insufficient but a second step
could provide support, including an injected timeout. It correctly stopped after exhausted evidence.
The cost was 1.57x retrieval calls.

Both systems generated on the time-of-day lexical blind spot even though booking evidence did not
answer the question. This is the most important Stage 3C result: retry improves recoverable recall,
but an incorrect Grader remains an unsafe shared failure boundary.

## Metric semantics

- Task success means generation when the scripted trajectory eventually contains sufficient
  evidence, or abstention when it never does.
- Unsupported generation means generation when the oracle says the evidence available at the used
  step is insufficient.
- Safe abstention means stopping when evidence available to that system is insufficient.
- Rewrite recovery is evaluated only on first-step-insufficient, eventually-sufficient cases.

Safe abstention is not interchangeable with task success: Direct RAG safely abstains on recoverable
cases but fails to complete the task. Per-case output preserves that distinction.

## Limits

The seven labels are project-authored drafts and are not independently reviewed. Scripted retrieval
does not measure ranking quality, provider latency, token cost, or real network behavior. Harness
runtime is intentionally not reported as production latency.

## Reproduce

```bash
./scripts/bootstrap.sh
travelmind eval-trajectory \
  --root . \
  --output evals/results/agentic_trajectory_rule_v1_seed.json
```
