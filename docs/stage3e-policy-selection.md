# Stage 3E: component-level selection gate

## Current decision

The real candidate and a Grader prompt ablation were run. Stage 3E selects a mixed stack:

- `LLMQueryRouter` using `router-v2-nonthinking`
- `CoverageEvidenceGrader`
- `MissingAspectQueryRewriter`

The Router passed quality and component fallback gates in two repeated runs. Grader v3 improved over
v2 but only matched deterministic test F1, so it failed the lift gate. The Rewriter has no real
trajectory evidence and remains deterministic. The decision is recorded in
`evals/results/deepseek_policy_status.json`.

## Gate

Router selection requires at least +0.10 absolute test accuracy. Grader selection requires at least
+0.05 absolute test F1. Both require fallback rate at or below 5%. Passing Router/Grader metrics does
not select the Rewriter: it must separately improve trajectory recovery without increasing
unsupported generation beyond the frozen baseline.

The numeric thresholds are initial engineering gates, not statistically calibrated production
thresholds. The tiny non-blind seed must be expanded and independently reviewed before a resume-grade
DeepSeek result.

## Why component-level selection

“Use one LLM everywhere” makes failures and costs difficult to attribute. Router, Grader, and
Rewriter solve different tasks and may have different winners. Keeping a deterministic component is
a valid final choice when an LLM does not justify its latency, token cost, or failure surface.

## Run the gate

```bash
travelmind select-agentic-policies --root .

# After a live candidate exists:
travelmind select-agentic-policies \
  --root . \
  --candidate evals/results/deepseek_policy_candidate_grader_v3_run2.json
```
