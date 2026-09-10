# ADR 011: separate labels for Agentic policy decisions

## Status

Accepted for the Stage 3B evaluation foundation.

## Context

Retrieval relevance, routing intent, and evidence sufficiency are different targets. The existing
retrieval query categories were created to compare rankers, not to supervise runtime control or
decide whether a specific evidence set supports generation.

## Decision

Maintain separate typed JSONL datasets for routing and evidence grading. Require fixed development
and test splits, stable identifiers, rationales, review metadata, reference validation, and a content
fingerprint in every report. Preserve the deterministic `rule-v1` result before policy tuning.

## Alternatives rejected

- Reuse retrieval query type as the routing answer: convenient, but it leaks an evaluator taxonomy
  into runtime behavior and cannot represent all control decisions.
- Let an LLM judge without labeled cases: fast to demo, but judge drift and self-preference make
  optimization unauditable.
- Report only end-to-end answer quality: hides whether failures came from routing, retrieval,
  sufficiency grading, rewriting, or generation.
- Randomly resplit on every run: produces unstable metrics and makes comparisons irreproducible.

## Consequences

The project can now compare deterministic and later LLM policies on the same explicit contracts.
The seed is deliberately too small and not independently reviewed, so it supports engineering and
error analysis only. More labels and an untouched test partition are required before tuning or
resume-grade quality claims.

## Fallback boundary

Label/evaluator failure must fail the offline experiment rather than emit partial metrics. At
runtime, unavailable LLM policies may fall back to deterministic ones, but the weak baseline shows
that availability fallback does not imply semantic correctness.
