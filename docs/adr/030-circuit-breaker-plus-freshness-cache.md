# ADR 030: combine a circuit breaker with a freshness-aware cache

Status: Accepted for Stage 7B pilot

## Context

Retrying every timeout can create a retry storm, while serving every cached result can publish stale
opening hours or routes as current. Availability and correctness require separate controls.

## Decision

Count only transient dependency failures in a thread-safe closed/open/half-open breaker. Hash cache
keys, deep-copy evidence snapshots, and divide cache use into fresh, bounded stale allowlisted, and
inadmissible states. Expose retrieval mode, cache age, circuit state, and degradation through the
diagnostic retrieval boundary and Stage 7A telemetry.

## Alternatives rejected

- **Retries only:** continue loading an unhealthy dependency and increase tail latency.
- **Cache everything until recovery:** unsafe for dynamic hard constraints.
- **Never use stale data:** unnecessarily removes useful static descriptions during short outages.
- **Add Redis immediately:** distribution does not define correctness; the local policy contract and
  state transitions need to be tested first.
- **Use a large resilience library immediately:** useful in production, but the current small state
  machine makes counting, half-open concurrency, and freshness semantics explicit for evaluation.

## Consequences

Sustained retrieval failure becomes fast and visible, and safe cached evidence can preserve partial
availability. More state now exists per dependency instance; production deployment must define
whether breakers are process-local or coordinated and must avoid one tenant opening another tenant's
circuit without a deliberate sharing policy.
