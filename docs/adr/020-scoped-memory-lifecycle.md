# ADR 020: separate scoped conversation memory from graph checkpoints

## Status

Accepted for the Stage 4E reference implementation.

## Decision

Use explicit tenant/user/thread scopes for TTL-bound short-term history and tenant/user scopes for
allowlisted, consented long-term preferences. Keep memory behind a narrow store protocol and treat
it as optional context. Keep LangGraph checkpoints separate.

## Alternatives

- Put all history in LangGraph state: convenient, but mixes recovery data with product memory and
  makes retention and deletion difficult.
- One user-level chat history: enables continuity but leaks content between unrelated trips.
- Store every inferred preference automatically: personalized, but surprising and privacy-heavy.
- Use a vector database for all memory: useful for large semantic recall, but unnecessary for a
  small typed preference set and harder to delete and override exactly.
- Fail the request when Redis is unavailable: preserves memory semantics but unnecessarily destroys
  stateless travel planning availability.

## Consequences

The system has explicit isolation, retention, consent, precedence, and deletion semantics. Reads can
degrade safely to stateless mode, while deletion cannot. Production Redis/PostgreSQL adapters still
need authentication, encryption, atomic deletion, observability, and failure-injection evidence.
