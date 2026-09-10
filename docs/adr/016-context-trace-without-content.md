# ADR 016: trace context decisions without storing prompt content

## Status

Accepted for Stage 4A.

## Decision

Separate `PackedContext`, which exists at the model boundary, from `ContextTrace`, which contains only
item IDs, kinds, token estimates, include/clip/drop actions, reason codes, and degradation signals.

## Alternatives

- Log the full prompt: simplest debugging, but duplicates user and evidence content into telemetry.
- Log only total tokens: safer, but cannot explain which evidence was dropped.
- Store hidden reasoning: unnecessary for control evaluation and creates privacy and stability risks.

## Consequences

Per-item decisions remain auditable without turning observability storage into a second sensitive
prompt store. Reproducing exact content requires the versioned source dataset and document IDs.
