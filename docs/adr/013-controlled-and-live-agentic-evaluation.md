# ADR 013: retain both controlled and live Agentic evaluations

## Status

Accepted after Stage 3C.2.

## Decision

Keep controlled scripted trajectories and live Hybrid RRF trajectories as separate experiments.
Do not combine their success rates or describe the controlled lift as end-to-end retrieval lift.

## Rationale

Controlled cases answer whether rewrite/retry can recover when useful evidence is available later.
Live cases answer how often that opportunity occurs with the current retriever and corpus. The first
showed 100% recovery on three eligible drafts; the second showed no quality lift and measurable
overhead because the only detected gap was missing from the corpus.

## Alternatives rejected

- Report only the positive controlled result: overstates real-world opportunity frequency.
- Report only the negative live result: incorrectly implies the mechanism cannot recover.
- Merge both datasets: destroys their different sampling semantics.
- Increase retry count until retrieval succeeds: cannot recover absent knowledge and increases cost.

## Consequence and fallback

The default retry budget remains two, and evidence exhaustion terminates safely. Future LLM policy
experiments must beat Direct Hybrid on new recoverable held-out cases and justify calls, latency,
invalid-output risk, and fallback frequency.
