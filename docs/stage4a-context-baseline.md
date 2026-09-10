# Stage 4A: context baseline and trace

## Outcome

TravelMind now builds a typed context from system instructions, the original user request,
structured constraints, and retrieved evidence. The unbounded baseline records estimated tokens per
item and category before any optimization.

`ContextTrace` stores IDs, kinds, token estimates, actions, and reason codes. It deliberately does
not store prompt content, user text, evidence text, API keys, or hidden reasoning. The packed context
retains content only for the immediate model boundary.

## Baseline

On the 15 fixed Hybrid RRF queries, packing all ten retrieved documents used an estimated mean 1,772
input tokens. This is a heuristic count, not a DeepSeek billing number. Default empty constraints are
excluded, while explicit hard filters remain mandatory context.

## Failure boundary

- A model-aware tokenizer may be injected later.
- If it raises, the estimator falls back to a deterministic mixed CJK/ASCII heuristic and marks
  `token_estimator` degraded.
- Error text is not copied into the trace.
- The trace never makes a model-context claim from provider output usage alone.

## Reproduce

```bash
travelmind eval-context --root . --output evals/results/context_budget_v1_seed.json
```
