# ADR 044: Use Redis for optional cache and shared checkpoints

## Decision

Retain Qdrant for vector retrieval and SQLite for zero-service local durability. Add Redis as an
optional Tool Cache and LangGraph Checkpoint backend selected explicitly at process startup.

## Cache policy

Only successful read-only idempotent tool responses may be cached. Candidate search uses a longer
TTL than availability and travel-time checks; booking requirements are not cached in the initial
policy. Mutating booking operations would be non-cacheable and require idempotency receipts.

Redis cache failures are bypassed because a cache is an optimization. Checkpoint failures are
fail-closed because silently changing checkpoint stores can fork history and duplicate side effects.

## Rejected alternatives

- Replacing Qdrant with Redis only to reduce technology count: no retrieval A/B justifies migration.
- Automatic Redis-to-SQLite failover mid-run: the stores do not share a committed execution history.
- Caching every tool result: dynamic availability and side effects make that unsafe.

## Evidence boundary

Unit and fault-injection checks cover TTL policy and cache outage bypass. A real Redis lifecycle probe
is implemented but remains uncommitted until a Redis 8 service is available locally.
