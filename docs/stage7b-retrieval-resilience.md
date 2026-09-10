# Stage 7B: circuit breaker and freshness-aware retrieval cache

## Outcome

Retrieval can now be wrapped by a thread-safe circuit breaker and a query-keyed TTL cache. Transient
timeouts and connection failures count toward the breaker; repeated calls during an open interval
fail fast without touching the unhealthy provider. After the recovery timeout, exactly one half-open
probe determines whether the circuit closes or reopens.

Cache keys are SHA-256 hashes of normalized queries and the result limit, so raw user text is not used
as the key. Evidence snapshots are deep-copied on write and read to prevent callers from mutating the
cached copy.

## Freshness safety

The policy has two distinct windows:

- Inside `fresh_ttl_seconds`, cached evidence can cover a transient retrieval outage.
- Between fresh TTL and `maximum_stale_seconds`, only evidence whose freshness class is explicitly
  allowlisted can be returned. The default allowlist contains only `static`.
- Beyond maximum stale age, all cache entries fail closed.

This means static descriptions may preserve degraded availability, while dynamic opening hours,
booking rules, prices, weather, and route estimates cannot become “current” merely because a cache
entry exists. The deterministic planning validator separately enforces freshness for operational
facts.

## Controlled drill

Eight state and policy checks passed:

1. healthy primary result populates cache;
2. first transient failure uses fresh cache and opens the circuit;
3. the next open-circuit request avoids a provider call;
4. stale dynamic evidence is rejected;
5. a half-open success closes and resets the circuit;
6. bounded stale static evidence remains available;
7. expired static evidence is rejected;
8. provider exception payloads are replaced by a typed sanitized boundary.

The measured check pass rate, fast-fail call avoidance, dynamic stale rejection, half-open recovery,
and bounded static availability were all 1.000 on deterministic fixtures.

## Why not only retries

Retries help isolated transient faults but amplify sustained outages. A breaker caps downstream load
and latency during an incident. Cache fallback is complementary: the breaker answers whether to call;
the freshness policy answers whether an older value is safe enough to use.

## Boundaries

- The breaker does not terminate a blocking Python call. Remote clients still need native connect,
  read, pool, and total deadlines.
- The reference cache is in-process. Redis needs serialization versioning, TTL atomicity, eviction,
  tenant isolation, encryption, and outage tests.
- The drill uses threshold `1` to expose transitions quickly; the reusable default is `3` and must be
  tuned from real error rates and traffic.
- Authentication, validation, and request-specific errors do not count as provider-health failures.
