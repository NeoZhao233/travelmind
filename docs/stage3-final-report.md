# Stage 3 final pilot report

## Selected runtime profile

- Router: DeepSeek `router-v2-nonthinking` when configured; deterministic fallback on failure.
- Grader: deterministic `CoverageEvidenceGrader`.
- Rewriter: deterministic `MissingAspectQueryRewriter`.
- Retrieval: BM25 + BGE dense + RRF, with bounded Multi-Query RRF on rewrite.
- Control: LangGraph with at most two retrieval attempts and explicit insufficient-evidence stop.

## Evidence chain

1. The rule Router exposed lexical brittleness: 0/5 on the draft test split.
2. Controlled trajectories showed rewrite recovery capability but a shared Grader safety boundary.
3. Live Hybrid evaluation showed no Agentic lift on a strong first-pass baseline and measured the
   added call/latency cost.
4. DeepSeek v1 with thinking enabled failed structured output and activated fallback.
5. Non-thinking v2 fixed output validity; Router reached 5/5 test cases while Grader regressed.
6. A development-driven Grader v3 recovered recall but only tied baseline test F1 in two runs.
7. Component gates selected only the Router.

The v1 report's 3,011 recorded tokens include only schema-valid calls. Schema-invalid responses had
already reached the provider but the original telemetry discarded their usage, so v1 total cost is
known to be underestimated and is not used for cost comparison. Telemetry now retains usage and
latency for post-provider validation failures; historical data is not fabricated retroactively.

## Repeated final candidate

| Metric | Run 1 | Run 2 |
| --- | ---: | ---: |
| Router test accuracy | 1.000 | 1.000 |
| Grader test F1 | 0.667 | 0.667 |
| Fallback rate | 0.000 | 0.000 |
| Total tokens / 26 calls | 6,716 | 6,732 |
| Mean successful-call latency | 970 ms | 865 ms |

## Claim boundary

Stage 3 is complete at pilot level, not benchmark level. The test split has five Router and five
Grader cases, was authored inside the project, and was observed during iteration. Resume wording
must describe the evaluation framework, negative results, fallbacks, and component selection; it
must not imply production accuracy or statistical significance.
