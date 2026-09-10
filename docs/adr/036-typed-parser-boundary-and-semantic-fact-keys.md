# ADR 036: typed parser boundary and semantic fact keys

Status: Accepted for Stage 8C

## Context

HTML/API parsers can emit malformed references, and different sources can disagree without sharing
fact IDs. Full index rebuilds are safe but expensive when one source changes.

## Decision

Treat parser output as untrusted candidate data, validate cross-record invariants, and quarantine
failures with sanitized metadata. Reconcile records under a value-independent semantic fact key after
freshness filtering. Group equivalent values before applying authority and observation-time
precedence; exclude unresolved conflicts. Update the reference fact index by copy-on-write recompute of
only keys affected by the changed source.

## Alternatives rejected

- **Trust parser dictionaries:** allows dangling document/place references into retrieval metadata.
- **Use fact ID as conflict key:** different publishers rarely share IDs, so conflicts stay invisible.
- **Include value in the key:** separates precisely the records that must be compared.
- **Pick a deterministic winner for every tie:** produces stable but unsupported facts.
- **Recompute every key on each update:** turns small source changes into full-index work.

## Consequences

The system has an auditable selected/unresolved decision for each semantic key and preserves serving
state on rejected updates. Semantic-key design and authority ranking are versioned domain policy.
Production needs durable transactions or versioned collection promotion, multi-writer control,
parser resource limits, and propagation of unresolved facts to answer abstention.
