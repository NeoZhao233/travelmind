# ADR 018: bounded coverage-aware evidence packing

## Status

Accepted for Stage 4C pilot.

## Decision

Infer requested fact aspects from the runtime query and hard filters, annotate evidence with typed
fact metadata, and add a bounded bonus for newly covered aspects before applying the Stage 4B token
packer. Keep retrieval priority as part of utility and as the complete fallback when coverage data
is absent.

## Alternatives

- Retrieval order only: simple and relevance-oriented, but the measured multi-constraint failures
  repeatedly spend budget on one fact type.
- Maximal marginal relevance over embeddings: useful for semantic diversity, but semantic distance
  does not guarantee coverage of required travel constraints.
- LLM-based evidence selection: flexible, but adds latency, cost, nondeterminism, and a new provider
  failure before a deterministic baseline exists.
- Unlimited coverage bonus: maximizes tags but can promote low-relevance, broadly labeled evidence.

## Consequences

The selector is deterministic, cheap, traceable, and improves the pilot without extra model calls.
Its Chinese query lexicon and typed-fact metadata can be incomplete. Missing signals degrade to rank
order; incorrect signals are bounded by the retrieval score and guarded by regression evaluation.
