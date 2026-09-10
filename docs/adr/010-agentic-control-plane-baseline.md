# ADR 010: Deterministic Agentic RAG control plane before LLM policies

## Status

Accepted for Stage 3A. LLM router, grader, and rewriter adapters remain Stage 3B experiments.

## Problem

Query routing, evidence grading, and query rewriting are often introduced as one prompt-driven
agent. That makes failures difficult to attribute: a final improvement could come from routing,
rewrite vocabulary, more retrieval calls, or accidental dataset leakage.

The project needs a bounded, traceable control plane before adding model variability.

## Decision

Create separate injected protocols for `QueryRouter`, `EvidenceGrader`, and `QueryRewriter`, and
orchestrate them with a LangGraph state machine. Establish deterministic rule and coverage policies
as the baseline and fallback. Store compact structured decisions and reason codes in state rather
than chain-of-thought.

Execute rewritten queries independently through `MultiQueryRRFAdapter`; deduplicate them, cap fanout
at four, and fuse document ranks. A list of rewrites must not be concatenated into one query because
that changes retrieval semantics and hides each query's contribution.

## Why LangGraph here

- Retrieval, grading, rewriting, and retrieval form a real conditional cycle.
- Maximum attempts provide an explicit termination proof.
- Each node has a small, independently injected policy boundary.
- State exposes trajectory, attempts, missing evidence aspects, degraded components, and failure
  reason for evaluation.
- Later checkpointing can resume node boundaries without storing clients or model objects in state.

## Why deterministic policies first

- They create a reproducible floor for routing and recovery behavior.
- Failure tests need no keys, network access, or probabilistic assertions.
- A later LLM policy must beat a named baseline on trajectory metrics.
- The same deterministic policies are safe fallbacks when model output is invalid or unavailable.

This is not a claim that keyword rules are the final intent classifier. Their expected brittleness
is a measurable reason to evaluate an LLM adapter in Stage 3B.

## Alternatives considered

- **One ReAct agent with all tools.** Fast to demo, but tool choice, retries, and termination are
  harder to constrain and evaluate independently.
- **Linear LCEL chain.** Suitable for a single pass, but the grade/rewrite retry cycle becomes
  implicit application code.
- **Hard-code Hybrid retrieval without routing state.** Simpler, but prevents trajectory evaluation
  and future strategy ablations.
- **LLM policies immediately.** Adds API/model variance before graph and fallback contracts are
  testable.
- **Concatenate all rewrites.** One call is cheaper, but query terms interfere and query-level
  attribution is lost.
- **Unlimited decomposition/retry.** May improve recall but creates latency, cost, and retry-storm
  risks. Query fanout and retrieval attempts are both bounded.

## Reliability policy

- Router failure uses deterministic Hybrid routing.
- Grader failure uses deterministic trusted-source and aspect-coverage checks.
- Rewriter failure expands only missing fact aspects with fixed official-source terms.
- Retriever failure enters the bounded grade/rewrite cycle; repeated failure terminates.
- State records only component and exception type, never provider error text.
- Multi-query retrieval tolerates partial query failure; all-query failure is explicit.
- No policy fallback may bypass deterministic itinerary validation.
