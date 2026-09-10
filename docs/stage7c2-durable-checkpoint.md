# Stage 7C.2: durable cross-process checkpoint and receipts

## Outcome

The local development profile now uses the official `langgraph-checkpoint-sqlite` saver with the
same strict TravelMind serializer allowlist as the in-memory pilot. A separate SQLite receipt store
uses `BEGIN IMMEDIATE`, a primary-key claim, owner identity, status, acquisition time, and typed
itinerary JSON.

The evaluation starts independent Python processes instead of rebuilding a graph in one process:

1. process A runs through `generate`, writes a checkpoint, and exits with `validate` pending;
2. process B opens the same database and completes `validate` with zero Planner calls;
3. process C executes and commits an idempotent Planner receipt;
4. process D opens the same receipt database and replays it with zero underlying Planner calls.

All six checks passed. Cross-process checkpoint resume, cross-process receipt replay, and owner-only
database file permissions were each 1.000 on the controlled drill.

## Technology choice

LangGraph documents `InMemorySaver` as testing-only, `SqliteSaver` as lightweight local/small-project
storage, and `PostgresSaver` as the production option with full checkpoint history. SQLite is selected
here because it can prove actual process-boundary persistence without requiring a database service.
It is not presented as the final multi-instance architecture.

The SQLite checkpointer package is an optional `checkpoint` extra because normal deterministic unit
tests and core agent execution should not require it. The import is lazy and the CLI reports the
bootstrap command when the extra is absent.

## Receipt transaction boundary

The receipt claim is committed before the external operation begins. A successful result is then
written only by the claim owner. A normal exception deletes that owner's in-progress claim so retry
is possible. An OS crash can leave an in-progress row; after its lease expires, the implementation
fails closed with `AbandonedReceiptError` instead of assuming the external effect did not happen.

This deliberately prefers operator reconciliation over an automatic duplicate side effect. Exactly
once still requires provider-side idempotency or a transaction shared with the external effect.

## Security and operations

- Database files are set to mode `0600`.
- Query/evidence content is not used as a receipt key; the key is a SHA-256 fingerprint.
- Custom checkpoint types use an explicit deserialization allowlist.
- SQLite busy timeout is bounded at five seconds and WAL mode is enabled.
- Production still needs encryption at rest, backup/restore, retention, migrations, tenant access
  checks, disk-full behavior, corruption recovery, and checkpoint pruning.

## Reproduction

```bash
./scripts/bootstrap.sh --extra dense --extra checkpoint
LANGGRAPH_STRICT_MSGPACK=true travelmind eval-durable-checkpointing --root . \
  --output evals/results/stage7c2_durable_checkpoint_v1.json
```

The official reference describes SQLite as lightweight synchronous storage that does not scale to
multiple threads, while PostgreSQL is the production workload option. That boundary is part of the
technology decision, not a hidden limitation.
