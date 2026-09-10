# ADR 014: DeepSeek JSON policies over a minimal HTTP boundary

## Status

Accepted and evaluated in Stage 3D.

## Decision

Use the official OpenAI-compatible Chat Completions endpoint through the existing `httpx` dependency.
Request JSON mode with thinking disabled for short control decisions, then validate the returned
object with local Pydantic schemas. Keep all three LLM
policies injectable and let the LangGraph runtime fall back to deterministic implementations.

## Alternatives

- LangChain model wrappers: useful for broad provider composition, but add abstraction and version
  behavior that is unnecessary for three small structured policy calls.
- OpenAI SDK against the compatible endpoint: valid, but would turn an optional integration into an
  extra runtime dependency; it can be added if streaming or richer compatibility becomes necessary.
- Prompt-only JSON without response format: has a larger parsing failure surface.
- Strict tool calling beta: stronger schema potential, but ties the baseline to a beta endpoint.

## Failure boundary

Retry only timeout, 429, 500, and 503 once. Reject empty, truncated, malformed, and semantically
inconsistent output. Store sanitized exception types, never response bodies or API keys. Availability
fallback does not prove semantic correctness, so fallback rate remains an evaluation metric.

The first live run confirmed this boundary: default thinking exhausted the small output budget and
all Router outputs were rejected as truncated. Disabling thinking changed structured-output success
from 6/26 to 26/26 and reduced mean successful-call latency.
