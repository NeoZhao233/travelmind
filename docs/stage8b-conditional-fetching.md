# Stage 8B: conditional source fetching and freshness policy

## Problem

Travel facts have different volatility. Re-downloading every official page wastes bandwidth and can
trigger rate limits, while treating old opening-hours or booking data like a static landmark
description can produce an infeasible itinerary.

## Fetch contract

The fetcher applies policy before the network boundary:

- only HTTPS URLs on an exact host allowlist, without credentials or non-443 ports;
- redirects stay disabled so a permitted URL cannot redirect to an unapproved target;
- timeout and maximum attempts bound each fetch;
- `ETag` and `Last-Modified` become conditional request headers;
- a `304` refreshes `validated_at` without creating new content;
- content type and byte count must pass before ingestion accepts a response.

Only transient transport errors, `429`, and `5xx` retry. Authentication, redirects, invalid content,
and oversized responses fail immediately. Backoff is exponential and capped; numeric `Retry-After`
is also capped so a source cannot block a worker indefinitely.

## Freshness-aware fallback

| Cached representation | Policy | Result |
| --- | --- | --- |
| Age within fresh TTL | Static or dynamic | Serve `cache_fresh`, disclose fallback |
| Beyond fresh TTL but within maximum stale | Static only | Serve `cache_stale`, disclose age |
| Beyond fresh TTL | Dynamic | Fail closed |
| Beyond maximum stale | Any | Fail closed |

Opening, booking, route, weather, and price should use dynamic policies. Historical descriptions may
be explicitly static. This classification belongs to typed fact/source policy, not an LLM decision.

## Evaluation

The controlled drill passed all eight checks: conditional revalidation, third-attempt recovery,
dynamic-stale rejection, bounded static availability, pre-transport URL blocking, and exception
payload redaction.

```bash
travelmind eval-source-fetching --root . \
  --output evals/results/stage8b_source_fetch_v1.json
```

## Remaining production work

Hostname allowlisting is not complete SSRF defense because DNS can resolve an allowed hostname to a
private address. Production needs resolution-time IP policy and DNS-rebinding protection. The current
adapter also checks size after download; streaming with a hard byte cap is required. Distributed rate
limiting, jitter, proxy policy, TLS decisions, and HTTP-date `Retry-After` remain outside this pilot.
