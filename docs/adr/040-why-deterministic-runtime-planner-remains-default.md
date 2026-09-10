# ADR 040: retain the deterministic runtime planner after DeepSeek A/B

Status: Accepted for Stage 11 pilot

## Context

An LLM replanner may generalize to unfamiliar failure combinations, but it also adds latency, tokens, schema
variance, and a new failure boundary. Stage 11 therefore evaluates DeepSeek as a replaceable
component, not as evidence that the whole system is agentic merely because an LLM chooses tools.

## Decision

Keep `DeterministicMultiStepRuntimePlanner` as the selected default. Retain `LLMRuntimePlanner` as an
optional candidate behind Pydantic parsing, tool/kind matching, place allowlists, stable plan identity,
runtime-owned arguments, bounded execution, and deterministic fallback.

The selection report separates model-plan acceptance from fallback-inclusive completion. It also
counts safe argument canonicalization: the runtime may replace a model-rewritten retrieval query with
the original user query, remove unsupported date fields, and restore the trusted origin, but those
changes remain visible as normalization rather than being called strict model success.

## Evidence

Three real DeepSeek runs exposed different boundaries:

1. Initial prompt: all seven JSON responses failed post-provider validation; downstream completion
   came entirely from fallback.
2. Exact argument prompt: all three recovery plans passed, but all four initial plans expanded the
   retrieval-tool arguments, leaving 42.9% accepted plans and 57.1% fallback.
3. Runtime canonicalization: 100% plans were accepted, fallback was zero, contract completion and
   safe-stop behavior matched the deterministic baseline, and mean accepted-call latency was about
   1.08 seconds. Only 57.1% were strict plans; 42.9% needed argument normalization, 5725 tokens were
   consumed, and measured contract lift was zero.

The third candidate fails the maximum 25% argument-normalization gate and the positive incremental-
value gate. A fallback-inclusive 100% is not treated as raw model quality.

## Alternatives rejected

- Select DeepSeek because the final task completion is 100%: this hides fallback and normalization.
- Disable strict tool schemas: unsupported parameters would reach real clients and turn planning
  variance into tool failure.
- Reject every safely canonicalizable plan: secure runtime-owned fields can be corrected, but the
  correction rate must remain an explicit quality metric.
- Remove deterministic fallback after one good run: the sample is four project-authored cases and
  cannot establish production reliability.

## Revisit condition

Reconsider selection after independently reviewed, broader failure cases show measurable recovery or
generalization lift, while raw acceptance, normalization, fallback, latency, token, and safety gates
all pass.
