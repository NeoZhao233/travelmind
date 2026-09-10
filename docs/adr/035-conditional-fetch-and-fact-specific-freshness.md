# ADR 035: conditional fetch and fact-specific freshness

Status: Accepted for Stage 8B

## Context

Unbounded fetching causes latency and rate-limit risk. A universal stale-cache rule is unsafe because
historical descriptions and same-day booking availability have different correctness windows.

## Decision

Use an injected transport with a synchronous HTTPX adapter, conditional HTTP validators, explicit
retry classification, capped exponential backoff, and typed static/dynamic freshness policies.
Disable redirects and apply URL policy before transport. Fail closed when dynamic evidence is older
than its fresh TTL or any cache exceeds its maximum stale age.

## Alternatives rejected

- **Always fetch without validators:** wastes source capacity and creates unnecessary failure surface.
- **Retry every error:** repeats authentication and validation bugs and amplifies outages.
- **Serve any last-known value:** can recommend closed, unavailable, or incorrectly priced activities.
- **Let the LLM decide whether evidence is stale:** makes a deterministic boundary probabilistic.
- **Add a generic retry library immediately:** the small explicit state machine is easier to inject,
  audit, and measure; a library is justified if policies become broader and shared.

## Consequences

The agent distinguishes validated unchanged content from unverified stale fallback and records
attempts, cache age, mode, and sanitized error type. Source owners must define fact-level freshness.
Production still needs streaming limits, resolved-IP SSRF controls, shared rate limits, jitter, and
real-source drills.
