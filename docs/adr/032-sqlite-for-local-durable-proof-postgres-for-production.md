# ADR 032: SQLite for local durable proof, PostgreSQL for production

Status: Accepted for Stage 7C.2

## Context

In-memory checkpointing cannot validate process restart. Running PostgreSQL for every local test adds
service provisioning and cleanup before the persistence contract itself is proven.

## Decision

Use the official synchronous `SqliteSaver` as an optional local adapter and test it across independent
Python processes. Keep checkpointer injection in the graph so production can substitute
`PostgresSaver`. Implement local SQLite itinerary receipts with atomic primary-key claims and
fail-closed abandoned leases.

## Alternatives rejected

- **Keep InMemorySaver:** proves graph semantics but loses all state at process exit.
- **Write a custom LangGraph SQLite saver:** duplicates a maintained official integration and its
  evolving checkpoint semantics.
- **Use SQLite as production multi-instance storage:** official guidance limits it to lightweight
  synchronous use; contention, growth, and operational recovery differ from PostgreSQL.
- **Require PostgreSQL for unit tests:** provides stronger deployment parity but slows the default
  feedback loop and couples ordinary tests to Docker/service availability.
- **Automatically steal expired receipts:** may duplicate an external action that succeeded before
  its receipt commit.

## Consequences

The repository now has honest cross-process evidence with no external service. Production deployment
still requires PostgreSQL integration, schema setup, pool/timeouts, migration ownership, retention,
and real outage drills. SQLite results cannot be used as PostgreSQL throughput claims.
