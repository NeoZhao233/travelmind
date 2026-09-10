# Stage 4B: deterministic token budget

## Contract

The context budget separates maximum context, reserved output, and estimator safety margin. System
instructions, the original request, and explicit constraints are mandatory. They are never silently
truncated: if they exceed input capacity, construction fails with `ContextBudgetError`.

Evidence follows retrieval priority, has a per-document cap, and may be clipped to remaining space
or dropped. Every action is visible in `ContextTrace`. This stage intentionally preserves retrieval
order; aspect-aware selection belongs to Stage 4C.

## Budget sweep

| Maximum context | Mean estimated input | Token reduction | Mean relevant-doc recall | Mean evidence count |
| ---: | ---: | ---: | ---: | ---: |
| 512 | 321.8 | 78.8% | 0.800 | 1.40 |
| 768 | 511.3 | 66.4% | 0.922 | 3.00 |
| 1024 | 670.7 | 55.9% | 0.922 | 4.07 |
| 1536 | 1012.9 | 33.4% | 0.978 | 6.47 |

The pilot gate selects the smallest configuration with mandatory preservation 1.0 and mean relevant
document recall at least 0.9, so 768 is selected. Its 192-token output reserve and 64-token safety
margin leave 512 estimated input tokens. The threshold is an engineering gate, not a calibrated SLA.

## Interpretation

Full URLs and internal aspect labels remain in provenance objects but are excluded from the prompt.
That metadata correction reduced the selected envelope from 1024 to 768. At 768, fixed-order packing
saves 66.4% of estimated input while retaining 0.922 mean relevant-document recall.

## Fallbacks

- Tokenizer failure: deterministic heuristic plus degradation trace.
- Mandatory overflow: fail closed; never alter the user's request.
- Optional evidence overflow: cap, clip, then drop with reason codes.
- Insufficient evidence after packing: downstream Grader must abstain or retrieve again.
- Output reserve exhaustion is prevented before calling the model.

## Reproduce

```bash
travelmind eval-context-sweep \
  --root . \
  --output evals/results/context_budget_sweep_v1_seed.json
```
