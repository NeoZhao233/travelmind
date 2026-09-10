# ADR 012: scripted retrieval for control-plane evaluation

## Status

Accepted for Stage 3C.

## Decision

Evaluate Direct and Agentic control with fixed per-attempt document IDs and allowlisted injected
errors. Use oracle sufficiency labels at every step, store complete Agentic traces, and report both
quality outcomes and retrieval-call amplification.

## Why

A live ranker changes both evidence and control decisions, making it difficult to attribute a gain
to rewriting rather than retrieval variance. Scripted steps create controlled counterfactuals: both
systems see the same first result, while only Agentic RAG may use the second.

## Alternatives

- Evaluate only with live Hybrid RRF: needed later for end-to-end validity, but weak for causal
  debugging of the control plane.
- Mock arbitrary text: simpler, but real corpus IDs preserve document validation and auditability.
- Count every abstention as success: unsafe because it hides recoverable task failures.
- Report only success rate: hides unsupported generation and added retrieval cost.

## Fallback boundary

Unknown document IDs, duplicate case IDs, invalid injected errors, or a missing dataset split abort
the evaluation. Runtime retrieval timeouts remain bounded and enter the existing rewrite/retry path.
