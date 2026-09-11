# ADR 043: Put MCP behind a governed Tool Registry
Tool exceptions are sanitized at the MCP server boundary. If MCP transport and the allowed local
path both fail, the bounded Runtime stops without emitting an unsupported itinerary.
## Decision

Use the official MCP Python SDK v2 behind the existing `ToolRegistry` interface. Keep tool allowlists,
cacheability, fallback eligibility, retry budgets, and final validation inside the TravelMind Harness.

## Why

MCP standardizes discovery, schemas, resources, and transports, but it does not decide whether a tool
is safe for this product. Keeping protocol and policy separate lets the Runtime use local, in-process
MCP, stdio, or Streamable HTTP tools without giving the model control over permissions.

Only connection and timeout failures may use an allowed local read-only fallback. A server-returned
business failure is an Observation and must stay visible to the replanner.

## Rejected alternatives

- Replacing every internal function with an MCP network hop: protocol overhead has no value for
  purely internal deterministic validation.
- Falling back on every exception: this can conceal permission rejection, bad arguments, or provider
  business rules.
- Exposing a reservation-creation tool as read-only: the current `booking` tool only checks rules.

## Failure boundary

Tool exceptions are sanitized at the MCP server boundary. If MCP transport and the allowed local
path both fail, the bounded Runtime stops without emitting an unsupported itinerary.
