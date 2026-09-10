# ADR 029: use allowlisted best-effort telemetry behind an injected sink

Status: Accepted for Stage 7A pilot

## Context

Fallbacks and retries can preserve user-visible success while dependencies degrade. Without common
correlation and stage signals, aggregate success hides chronic fallback. Raw logging would expose
queries, evidence, prompts, provider responses, and exception payloads.

## Decision

Emit versioned events through an injected sink with one per-run trace ID and monotonic sequence.
Allow only bounded operational attributes; record exception type but not message. Sink failure never
changes planning correctness, but sets a typed `telemetry_degraded` result flag.

## Alternatives rejected

- **Raw structured dictionaries:** flexible but cannot enforce schema or redaction centrally.
- **Exporter SDK calls throughout domain code:** couples business logic to one observability vendor.
- **Fail the itinerary when export fails:** reduces availability even though telemetry is not a
  correctness dependency.
- **Ignore export failure completely:** makes an observability blackout indistinguishable from health.

## Consequences

The pipeline can expose retrieval fallback and stage latency without storing user content, and a sink
outage does not block the trip plan. Debug detail is intentionally lower; deep reproduction relies on
versioned inputs and hashes. Remote delivery reliability remains an adapter responsibility.
