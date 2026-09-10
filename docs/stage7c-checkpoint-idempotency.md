# Stage 7C: checkpoint resume and idempotency boundaries

## Outcome

The Agentic LangGraph builder now accepts an injected checkpointer and explicit interrupt points. In
the controlled run, execution stopped after `generate`, persisted `validate` as the next node, rebuilt
the compiled graph, and resumed to completion without calling the Planner again.

Checkpoint serialization runs with an explicit TravelMind module/class allowlist under
`LANGGRAPH_STRICT_MSGPACK=true`. This avoids both future failure from unregistered custom Pydantic
types and the unsafe alternative of permitting arbitrary module deserialization.

An independent idempotency receipt boundary hashes tenant/user/thread scope, operation, Planner
version, request, evidence IDs, and evidence content hashes. A completed receipt replays a deep copy;
an in-progress duplicate is rejected rather than executed concurrently.

## Controlled drill

Six checks passed:

1. graph interrupted after `generate` with `validate` recorded as next;
2. a rebuilt graph resumed to completion;
3. Planner call count remained one across resume;
4. a repeated idempotent Planner request replayed its receipt with one underlying execution;
5. checkpoint-backend failure stopped the resumable run;
6. only sanitized `ConnectionError` type entered diagnostics.

Logical resume success, duplicate-execution prevention, and checkpoint-outage safe failure were all
1.000 on deterministic fixtures.

## Why checkpointing is not idempotency

A checkpoint says which graph state was durably observed. It cannot guarantee an external side
effect happened exactly once. If a model/provider call succeeds and the process dies before saving
the next checkpoint, the node can run again. An idempotency receipt reduces this duplicate window,
but there is still an ambiguous interval between external success and receipt commit unless the
provider accepts an idempotency key or the effect and receipt share one transaction.

## Thread identity

Checkpointed invocation requires an explicit `thread_id`. Production identity should be scoped by
tenant, user, and conversation/run rather than a guessable global chat number. A trace ID correlates
telemetry; an idempotency key deduplicates one operation; a thread ID locates workflow state. They
have different lifecycles and must not be used interchangeably.

## Boundaries and next step

- `InMemorySaver` proves logical interruption/resume and serializer compatibility. Stage 7C.2 now
  proves local cross-process recovery with SQLite; machine-loss recovery is still outside scope.
- The in-memory receipt store proves atomic single-process semantics, not distributed uniqueness.
- Durable production deployment needs a PostgreSQL-backed saver for multi-instance service, plus
  encryption, migrations, retention,
  tenant authorization, cleanup, and outage drills.
- A crash after external success but before receipt commit remains ambiguous and must be documented
  per provider.
