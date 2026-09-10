# ADR 021: select the 768-token refined-coverage pipeline

## Status

Accepted for the Stage 4 pilot.

## Decision

Select the refined-coverage context pipeline with a 768-token envelope. Exclude full source URLs and
internal selection labels from model-visible metadata while retaining them in provenance objects.
Keep the unbounded path only as an evaluation control and emergency diagnostic mode.

## Evidence

The final real DeepSeek A/B reduced total tokens from 6589 to 3605, raised task success and citation
precision/recall from 0.857 to 1.000, removed fallback from 0.143 to zero, and slightly reduced mean
successful-call latency. Offline evidence coverage remained 1.000 with 0.944 relevant-document
recall.

## Alternatives

- Unbounded context: maximal evidence recall, but higher cost and an observed output failure.
- Priority-only budget: cheaper, but duplicated fact aspects reduce multi-constraint coverage.
- 1024-token refined context: more capacity, but 768 passes the quality gate after metadata cleanup.
- Generative compression: potentially smaller and more fluent, but adds hallucination and outage
  risks before independent evidence supports it.

## Consequences

The runtime has a measurable default and deterministic fallbacks. The result remains provisional
until a larger independently reviewed held-out set, repeated provider runs, and sentence-level
citation entailment evaluation are available.
