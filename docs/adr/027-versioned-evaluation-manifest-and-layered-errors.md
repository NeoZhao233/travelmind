# ADR 027: use a versioned governance manifest and layered error taxonomy

Status: Accepted for Stage 6 pilot

## Context

Stage 5 produced end-to-end metrics, but its five labels were project-authored and the report only
showed aggregate results. Calling a hand-created partition “held-out” would overstate independence,
while optimizing from one success number would not reveal which layer failed.

## Decision

Keep task labels immutable and add a separate, hashed governance manifest containing split,
authorship, reviewer identity, and review status. Require development and test partitions, reject
cross-split query/scenario collisions, and expose whether the test labels are independently
reviewed. Audit reports attach deterministic, possibly multiple, issue codes to every case and
aggregate them by variant and split.

## Alternatives rejected

- **Put `split` directly into the task file:** workable, but governance changes would alter the task
  dataset hash and blur label changes with review workflow changes.
- **Use only an experiment tracker:** useful later, but it cannot validate semantic leakage or false
  review claims by itself and adds infrastructure before the contract is stable.
- **Use only LLM-as-Judge:** non-deterministic scoring cannot replace exact constraint, provenance,
  fallback, or schema checks; without human calibration it can add confident noise.
- **Force one root-cause label:** failures can propagate across layers. Multi-label symptoms retain
  evidence and avoid pretending the evaluator knows causality.

## Consequences

Experiments now fail closed when their dataset fingerprint is stale and reports cannot silently call
the current test split blind. The added metadata and checks increase maintenance. Some taxonomy
labels, especially unexpected selection, remain diagnostics because the reference set is incomplete.
