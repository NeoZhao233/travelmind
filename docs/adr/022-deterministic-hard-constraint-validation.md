# ADR 022: keep hard travel constraints outside the LLM

## Status

Accepted for Stage 5A.

## Decision

Use Pydantic contracts for itinerary and operational facts, then use deterministic Python to
validate costs, dates, intervals, evidence, opening status, hours, and booking state. Treat the LLM
as a candidate generator. Unknown or stale operational facts fail closed for the affected activity.

## Why

Hard constraints need repeatable outcomes, exact reason codes, cheap retries, and provider-outage
independence. A model may explain a violation, but must not decide whether `120 > 100` or silently
turn missing opening-hours evidence into “probably open.” Recomputing totals also prevents a model
from bypassing the budget with an inconsistent aggregate.

## Alternatives

- LLM self-critique: useful for soft quality but nondeterministic and not an authority for facts.
- CP-SAT immediately: potentially stronger for global optimization, but premature until Stage 5B
  defines candidate variables, travel-time edges, and objective weights.
- rules inside LangGraph nodes: couples domain policy to orchestration and makes isolated testing
  harder; an injected validator keeps the boundary reusable.
- fail open on missing availability: improves completion rate but can recommend a closed place.

## Consequences

The planner exposes typed, locally repairable failures and remains safe during LLM outages. It also
needs trustworthy, fresh availability adapters; strict validation may return a partial plan or
abstention when those adapters are unavailable. Stage 7 must test real data-source outages and
freshness thresholds.
