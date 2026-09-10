# ADR 033: synthetic SLO gates before production SLOs

Status: Accepted for Stage 7D

## Context

Single-component unit tests do not prove that fallbacks compose safely. At the same time, local
failure injection cannot support claims about production availability or latency percentiles.

## Decision

Add deterministic multi-dependency outage scenarios to the release suite. Classify the thresholds as
`synthetic_pre_release_gate`, record degraded completion separately from healthy completion, and fail
closed when every evidence path is unavailable. Keep latency limits deliberately broad and retain raw
local measurements without calling them percentiles.

## Alternatives rejected

- **Count any completed fallback as healthy:** hides chronic dependency failure and destroys the
  signal needed for operational response.
- **Claim a production SLO from fixture runs:** lacks a time window, traffic distribution, sample
  size, and real infrastructure behavior.
- **Always return an itinerary:** converts an availability problem into unsupported recommendations
  when both retrieval paths fail.
- **Test only one outage at a time:** misses interactions among fallback execution, telemetry loss,
  and safe-failure handling.

## Consequences

The project now has an executable pre-release reliability contract and honest claim boundary.
Deployment still needs observed service-level indicators, alerting, capacity tests, distributed
dependency faults, and error-budget policy.
