# ADR 031: pair LangGraph checkpoints with scoped idempotency receipts

Status: Accepted for Stage 7C logical-resume pilot

## Context

Resuming a graph prevents already-checkpointed nodes from rerunning, but a crash can occur after an
external call and before the checkpoint commit. Checkpointing alone is therefore not exactly-once
execution.

## Decision

Inject the LangGraph checkpointer, require explicit thread identity, use a strict internal-type
serializer allowlist, and wrap costly or side-effecting operations with scoped, versioned,
content-fingerprinted idempotency receipts. Reject concurrent in-progress duplicates. Fail closed
when a run explicitly requiring persistence cannot write its checkpoint.

## Alternatives rejected

- **Checkpoint only:** leaves the post-effect/pre-checkpoint duplicate window unaddressed.
- **Receipt only:** cannot restore graph state or determine the next node.
- **Reuse trace ID for everything:** correlation, state identity, and operation deduplication have
  different scopes and rotation requirements.
- **Allow all deserializable modules:** convenient but unnecessarily broadens object-construction risk.
- **Claim exactly once:** impossible without provider idempotency or a shared transactional boundary.

## Consequences

Logical resume avoids repeating the Planner after a saved `generate` node, and same-input retries can
replay completed output. State and receipts require retention, deletion, authorization, schema
migration, and durable storage policies before production deployment.
