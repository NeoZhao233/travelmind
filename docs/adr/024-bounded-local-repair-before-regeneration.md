# ADR 024: use bounded local repair before full regeneration

## Status

Accepted for Stage 5C.

## Decision

Map typed violations to deterministic repair scopes and orchestrate at most two repair attempts in
LangGraph. Preserve unaffected days. Revalidate independently after every change. Fail immediately
for violations without a safe local strategy, and retain deterministic repair as fallback for any
future LLM or solver repairer.

## Alternatives

- regenerate the whole itinerary: simple, but discards valid work, increases model cost, and can
  introduce new failures on previously correct days;
- unlimited self-reflection: may loop, amplify provider cost, and still cannot certify hard
  constraints;
- accept the repairer's self-assessment: violates the separation between proposal and validation;
- retry unsupported violations: consumes budget without changing the state.

## Consequences

Repair cost and blast radius are bounded, unchanged days are measurable, and provider failure has a
deterministic path. Day-level replanning is not always the theoretical minimum change, and some
global constraints may still require full regeneration in a later explicitly gated fallback.
