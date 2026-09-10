# Stage 7A: privacy-safe structured observability

## Outcome

The end-to-end planning pipeline now emits versioned structured events for the pipeline, primary and
fallback retrieval, context construction, candidate construction, planning, and repair. One 32-hex
`trace_id` correlates every event and is also returned in the typed result. Sequence numbers make
missing or reordered local events visible.

Telemetry attributes use a strict allowlist of counts, status, and fallback signals. User queries,
prompts, evidence text, URLs, model responses, and exception messages are not accepted. Exceptions
record only their type. Unknown attributes are dropped and counted.

## Failure policy

Observability is best-effort and never owns business control flow. If the sink raises, planning
continues and the result marks `telemetry_degraded=true`. This preserves availability without calling
the situation healthy. Authentication, hard constraints, and evidence validation would fail closed;
telemetry export fails open because it does not determine itinerary correctness.

## Controlled drill

| Scenario | Business result | Expected signal |
| --- | --- | --- |
| Healthy | completed | contiguous correlated stage events |
| Telemetry sink outage | completed | `telemetry_degraded=true` |
| Primary retriever timeout | completed via BM25 fallback | failed primary span, safe `TimeoutError`, degraded retriever |

All three business runs completed, no canary appeared in an event or result, available-sink trace
integrity was 1.000, telemetry-outage survival was 1.000, and retrieval fallback visibility was
1.000. These are three fixture probes, not production SLO measurements.

## Alternatives

- Logging raw prompts would simplify debugging but creates privacy, secret, retention, and cardinality
  risks. Reproduction should use dataset IDs and content hashes instead.
- Depending directly on LangSmith or OpenTelemetry APIs would couple domain code to an exporter. The
  current sink protocol keeps the event contract injectable; an OTLP adapter can be added later.
- Silently swallowing sink errors would preserve uptime but hide loss of observability. The explicit
  result flag lets API and alerting layers disclose the degraded state.

## Remaining production work

Stage 7B will add circuit breaking and degradation policy. A remote exporter still needs bounded
queues, batch limits, drop counters, shutdown flushing, cardinality budgets, sampling, retention,
and transport timeouts. Trace IDs are correlation identifiers, not authentication or idempotency keys.
