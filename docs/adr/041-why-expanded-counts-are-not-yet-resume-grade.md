# ADR 041: Expanded counts do not replace independent review

## Status

Accepted.

## Context

The first retrieval and runtime datasets were too small for broad percentage claims. Expanding them
is necessary, but automatically treating paraphrases or generated fault combinations as independent
real-world observations would create false confidence.

## Decision

- Record `intent_id` and keep all paraphrases of one intent in the same development/test split.
- Report both query count and effective intent-cluster count.
- Bootstrap retrieval intervals over intent clusters rather than individual paraphrases.
- Mark Codex-authored labels as `reviewed=false` and block candidate promotion on missing review.
- Treat runtime combinations as deterministic contract coverage, not statistical reliability data.
- Preserve negative findings, including zero raw abstention accuracy.

## Alternatives rejected

**Report 105 independent queries.** Rejected because three variants share one label intent and are
correlated.

**Use the test split to tune the abstention threshold.** Rejected because it would leak evaluation
labels into selection and inflate the result.

**Mark generated labels reviewed after schema validation.** Rejected because structural validation
does not verify relevance judgments.

**Avoid publishing the zero-abstention result.** Rejected because it explains why ranking metrics
alone are insufficient and motivates a separate evidence-admission boundary.

## Interview answer

The expansion makes the evaluation more diagnostic, not automatically trustworthy. The honest unit
is 35 intent clusters, labels are still AI-authored drafts, and promotion remains blocked until a
person reviews them. This separates reproducibility and coverage from label validity.
