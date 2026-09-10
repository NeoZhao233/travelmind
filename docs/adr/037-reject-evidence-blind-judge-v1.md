# ADR 037: reject evidence-blind Judge v1

Status: Accepted

## Context

The first reference-only calibration completed all 21 model calls but failed the predeclared metrics.
The Judge saw citation IDs without the cited text, while the packet contained almost exclusively
high-quality answers.

## Decision

Reject Judge v1 and retain its report. Any v2 study must expose bounded cited evidence, include
stratified high/medium/low outputs, separate development from held-out cases, and preserve label
provenance. AI-assisted references can produce diagnostics but cannot satisfy a human-calibration gate.

## Alternatives rejected

- **Lower the thresholds after seeing results:** converts the test set into a tuning set.
- **Rerun until a favorable sample appears:** hides the measured repeat instability.
- **Treat citation IDs as evidence:** the Judge cannot verify claim support from opaque identifiers.
- **Call AI-assisted scores human labels:** misstates provenance and creates a circular claim.

## Consequences

The project has an honest negative result rather than an accepted subjective metric. V2 requires a
new dataset before prompt optimization. Deterministic safety and regression gates remain unaffected.
