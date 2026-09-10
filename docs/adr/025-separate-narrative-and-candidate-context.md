# ADR 025: separate narrative evidence from the planning candidate plane

## Status

Accepted in Stage 5D after offline end-to-end error analysis.

## Decision

Keep raw narrative evidence under the selected 768-token refined-coverage budget, while retaining a
separate typed candidate plane for every retrieved place-linked record. Require provenance on every
candidate. Use the candidate plane for feasibility and compact LLM ranking; use narrative context
for grounded language understanding.

## Alternatives

- derive candidates only from packed raw text: simple, but reduced multi-day task success to 0.8;
- increase the global prompt budget: may recover breadth but raises cost and repeats structured data;
- allow the model to invent omitted candidates: breaks retrieval grounding;
- put every raw document in the prompt: recreates the unbounded-context failure mode from Stage 4.

## Consequences

Candidate recall is no longer accidentally controlled by a QA-oriented text envelope, while model
input remains bounded. The system now has two related context contracts and must preserve provenance
between them. Candidate-plane quality needs its own recall and stale-fact evaluation in Stage 6.
