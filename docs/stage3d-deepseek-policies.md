# Stage 3D: optional DeepSeek policies

## Outcome

TravelMind provides optional DeepSeek-backed Router, evidence Grader, and query Rewriter adapters
behind the existing policy protocols. A real API candidate was evaluated after the offline failure
suite passed. Thinking mode caused output truncation in v1; non-thinking mode produced valid JSON
for all 26 calls.

## Contract

- Direct `httpx` call to the OpenAI-compatible `/chat/completions` endpoint.
- JSON mode, temperature zero, explicit JSON examples, and bounded output tokens.
- Pydantic validation after JSON parsing; valid JSON alone is not trusted.
- Default model `deepseek-v4-flash` and base URL are configuration, not domain constants.
- One bounded retry for timeout, HTTP 429, 500, or 503; other 4xx failures do not retry.
- Empty content, truncated output, invalid envelopes, non-object JSON, and inconsistent Grader
  decisions fail closed into the deterministic policy fallback.
- API keys are environment-only and excluded from object representations, state, errors, and reports.
- Telemetry records component, prompt version, model, latency, provider attempts, tokens, success,
  and sanitized error type.

## Reproduce the live candidate

```bash
export DEEPSEEK_API_KEY="..."
travelmind eval-deepseek \
  --root . \
  --model deepseek-v4-flash \
  --output evals/results/deepseek_policy_candidate.json
```

The evaluation executes 15 Router and 11 Grader cases with production-style deterministic fallback.
Fallback-inclusive quality and raw fallback rate must be reported together. Rewriter adoption still
requires trajectory-level retrieval recovery evaluation.

## Real result

- Router v2: test accuracy 1.000 in two repeated runs, up from rule baseline 0.000.
- Grader v3: test F1 0.667 in both runs, equal to the rule baseline and therefore rejected.
- Both v3 runs had 0% fallback; total tokens were 6,716 and 6,732.
- Mean successful-call latency was 970 ms and 865 ms.

The test split contains only five non-blind, project-authored cases and was observed during prompt
iteration. These are pilot engineering results, not production accuracy claims.
