# ADR 026: retain the deterministic planner after the DeepSeek A/B

## Status

Accepted for the Stage 5 pilot.

## Decision

Keep `explainable-greedy-v1` as the selected planner. Retain the DeepSeek shortlist adapter behind
the same strategy interface but do not enable it by default.

## Evidence

On five real Hybrid RRF pipeline cases, both variants reached 1.0 task success, validity, constraint
satisfaction, and required-place coverage. Both had 0.933 expected-place hit rate and identical final
place sequences. DeepSeek added 4475 tokens and about 877 ms mean provider latency, with zero
quality lift. It therefore failed the predeclared 0.05 lift requirement.

## Alternatives

- select DeepSeek because integration succeeded: confuses API validity with product value;
- select on subjective fluency: this component ranks IDs and does not generate the final narrative;
- remove the adapter: would discard a tested boundary useful for harder future preference cases;
- let DeepSeek own hard scheduling: would weaken deterministic safety and outage behavior.

## Consequences

The default remains cheap, reproducible, and provider-independent. Future LLM evaluation needs a
larger independently reviewed preference dataset with cases where semantic trade-offs can exceed
the heuristic baseline.
