# ADR 034: immutable snapshots and blue-green indexes

Status: Accepted for Stage 8A

## Context

Live travel sources change, parsers regress, and embedding jobs fail partway through. Mutating the
active index in place can expose mixed versions and makes rollback or answer reproduction difficult.

## Decision

Retain content-addressed raw snapshots, build each index version outside the serving path, validate it,
then atomically promote a pointer. Quarantine rejected builds and preserve previous complete builds for
rollback. Use a local filesystem adapter to prove the lifecycle before adding remote infrastructure.

## Alternatives rejected

- **Update the active index document by document:** exposes partial generations and makes readers see
  inconsistent state.
- **Store only parsed records:** loses the raw input required to debug parser changes and reproduce
  derived facts.
- **Rebuild during rollback:** repeats the potentially broken parser/model and increases recovery
  time; pointer rollback is deterministic and bounded.
- **Require Qdrant or object storage in unit tests:** improves infrastructure parity but weakens the
  default deterministic feedback loop.

## Consequences

Storage use grows because versions are immutable, so retention and garbage collection must respect
audit and rollback windows. Production adapters need conditional promotion, multi-writer ownership,
signing, encryption, access control, and orphan-build reconciliation.
