# ADR 028: freeze release gates and require measurable lift from paid components

Status: Accepted for Stage 6 pilot

## Context

A candidate can preserve correctness while adding latency, tokens, and provider failure modes. A
quality-only or schema-validity gate would have accepted the final DeepSeek ranker even though its
selected itineraries were identical to the deterministic baseline.

## Decision

Store a versioned gate profile outside implementation code and pin the exact baseline audit hash.
Require non-decreasing quality on every governed split, zero forbidden safety symptoms, bounded
fallback/cost/latency, and at least 0.05 expected-place hit-rate lift whenever provider tokens are
introduced. Return a nonzero CLI status when any check fails.

## Alternatives rejected

- **Only compare aggregate task success:** hides split regressions and partial preference misses.
- **Allow any non-regressing model:** makes latency, tokens, and new outage modes free in the decision.
- **Tune the lift threshold after seeing the candidate:** converts a gate into result-fitting.
- **Block all provider use:** rejects future models even if they create meaningful measured value.
- **Add LLM Judge quality now:** the calibration packet is still unlabeled, so subjective scores are
  not yet admissible release evidence.

## Consequences

The deterministic planner passes and the zero-lift DeepSeek ranker is reproducibly rejected. A paid
candidate can still be selected later, but it must earn its operational complexity. The 0.05 lift
and resource ceilings need reevaluation only with a deliberately versioned profile and a larger,
independently reviewed dataset.
