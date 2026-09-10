# Stage 7D: pre-release SLO and composite outage drill

## Outcome

The final Stage 7 drill executes three end-to-end scenarios against the same typed planning path:

1. a healthy deterministic control;
2. simultaneous primary-retrieval, model-ranking, and telemetry-sink outages;
3. simultaneous primary and fallback retrieval outages.

The recoverable composite case completed through BM25 retrieval fallback and deterministic planning
while reporting retrieval, model, and telemetry degradation. The unrecoverable retrieval case
returned a typed safe failure without an itinerary. All seven checks passed and the injected canary
leak rate was zero.

## Why these are pre-release objectives, not a production SLO

An SLO describes service behavior over an observation window and traffic population. This drill has
one local sample per controlled scenario, so it cannot establish availability or p95/p99 latency in
production. Its thresholds are release gates that catch missing fallbacks, invisible degradation,
unsafe continuation, and accidental secret exposure before deployment.

Production measurement still needs request-volume-weighted success semantics, sliding windows,
separate healthy/degraded/error budgets, percentile histograms, alert burn rates, and enough samples
to distinguish regressions from noise.

## Failure policy

| Fault set | Expected behavior | Safety boundary |
| --- | --- | --- |
| Primary retrieval + model + telemetry | Complete with BM25 and deterministic planner | Mark every degraded capability |
| Primary + fallback retrieval | Return failed result | Never plan without place-linked evidence |
| Exception text contains a canary | Emit only error type and stable reason | Never expose payload or query in output/telemetry |

Fallback completion is not counted as healthy. A high degraded-completion rate would consume a
separate operational budget and alert even if user-visible completion remained high.

## Reproduction

```bash
travelmind eval-slo-outages --root . \
  --output evals/results/stage7d_slo_outage_v1.json
```

The generated report records objective type, thresholds, per-case outcome, measured local latency,
configuration hash, and limitations.
