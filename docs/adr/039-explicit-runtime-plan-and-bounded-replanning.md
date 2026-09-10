# ADR 039: explicit runtime plans and bounded replanning

Status: Accepted for Stage 11 pilot

## Context

The Stage 3 graph can rewrite a weak retrieval query, and Stage 5 can locally repair an invalid
itinerary. Both loops are useful, but the route is still fixed in code. There is no runtime plan that
records intended tool calls, no typed observation boundary, and no way to replace future steps after
an external tool makes the original plan infeasible. Calling that behavior fully agentic would
overstate the implementation.

## Decision

Add a separate LangGraph runtime with an explicit, versioned `ExecutionPlan`. Each step declares its
tool, typed purpose, arguments, dependencies, status, and attempt count. Execution produces a
sanitized `ToolObservation`; the transition policy retries only transient failures and sends
permanent or schema failures back to the planner. A replacement must have a monotonically increasing
revision. Replans, attempts, and total calls are bounded; exhaustion ends in an explicit safe failure.

Keep failure attribution typed by layer: retrieval, tool, generation, validation, or orchestration.
Preserve a primary cause plus contributing reason codes rather than manufacturing certainty when
several stages contributed.

## Alternatives rejected

- **Add more conditional branches to the old graph:** improves a fixed workflow but still has no
  inspectable runtime plan or plan revision.
- **Retry every exception:** retries credentials, invalid schemas, and policy rejection pointlessly;
  it also risks storms and repeated side effects.
- **Let the LLM emit arbitrary tool calls until it stops:** looks agentic but has weak cost,
  termination, and safety guarantees.
- **Treat local output repair as replanning:** repair changes the artifact; replanning changes the
  strategy and remaining actions after an observation.
- **Ask an LLM judge to assign every root cause:** flexible, but non-deterministic and unable to
  establish transport or provenance facts that the runtime already knows.

## Consequences

The project can show a concrete plan revision after a failed tool and distinguish it from a retry.
The runtime is more verbose and needs explicit tool contracts. The first pilot is an injected,
deterministic proof, not evidence that an LLM planner is production-safe. Before selection as the
default path, Stage 11C must compare task recovery, incorrect replan, call cost, latency, and safe-stop
rates against the existing pipeline.
