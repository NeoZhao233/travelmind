# Stage 4E: scoped memory isolation and lifecycle

## Boundaries

TravelMind separates three kinds of state:

| State | Scope | Lifetime | Purpose |
| --- | --- | --- | --- |
| LangGraph execution state | one graph run/checkpoint | run or recovery window | node progress, retries, evidence |
| Short-term conversation memory | tenant + user + thread | 30-minute per-turn TTL, capped turns | conversational continuity |
| Long-term preference | tenant + user | until explicit deletion | consented pace/interests preferences |

A checkpointer is not a user-memory database. Resuming a failed node and remembering that a user
likes relaxed travel have different schemas, retention policies, and deletion obligations.

## Implemented contract

- `MemoryScope` requires explicit `tenant_id`, `user_id`, and `thread_id`.
- Storage uses tuple keys, avoiding ambiguous concatenated-key collisions.
- Short-term history is TTL-bound, capacity-bound, and idempotent on `turn_id`.
- Long-term preferences require explicit consent and an allowlisted key.
- Older preference events cannot overwrite a newer stored value.
- Current-request fields remove matching stored preferences before prompt construction.
- Thread deletion preserves other threads and user preferences; user deletion removes both.
- Memory context is optional and enters the existing token budget as `HISTORY`, never mandatory.

The current `InMemoryMemoryStore` is a deterministic reference adapter. A production implementation
would typically use Redis for TTL conversation history and PostgreSQL for durable, auditable user
preferences. Both must implement the same store contract before being selected.

## Outage semantics

Read failure returns an empty snapshot marked `memory_store` degraded, allowing a stateless answer.
Write failure returns `persisted=false`; the product must not tell the user that memory was saved.
Deletion failure raises `MemoryDeletionError` because falsely claiming data was forgotten is a
privacy violation. Error details are sanitized.

## Controlled evaluation

Fourteen deterministic probes cover cross-thread, cross-user, and cross-tenant isolation; owner
read, TTL, capacity, idempotency, consent, allowlisting, current-request precedence, stale writes,
and read/write/delete outages.

| Metric | Result |
| --- | ---: |
| Cross-scope leakage rate | 0.000 |
| Lifecycle probe accuracy | 1.000 |
| Privacy probe accuracy | 1.000 |
| Outage probe accuracy | 1.000 |

This proves reference-store semantics, not Redis ACLs, distributed consistency, encryption, or
network failure behavior. Those require adapter-specific integration and outage tests in Stage 7.

## Reproduce

```bash
travelmind eval-memory \
  --output evals/results/memory_isolation_controlled_v1.json
```
