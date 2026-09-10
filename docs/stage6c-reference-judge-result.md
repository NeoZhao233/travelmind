# Stage 6C reference-only Judge result

## Decision

Reject the v1 DeepSeek Judge for evaluation use. The run is retained as a negative experiment and is
not described as human calibration because its reference labels are `ai_assisted_unverified`.

## Measured result

- 21 of 21 provider calls returned schema-valid scores; fallback rate was 0.
- Exact four-score repeat consistency was 0.857, above the 0.80 stability threshold.
- Every dimension had within-one agreement of 0.857, below the required 0.90.
- Clarity/actionability MAE was 0.857, above the maximum 0.75.
- Weighted kappa ranged from -0.086 to 0.319, below 0.60 in every dimension.
- Mean bias was negative in every dimension, showing a harsher Judge on this seed.
- Total usage was 6,827 tokens; mean provider latency was approximately 1,123 ms per call.

## Error analysis

The accessibility/budget case received `(1,1,1,1)` on all three repeats. The Judge required multiple
options even though the query requested one place to prioritize. The inner-garden answer received two
`(5,5,5,5)` vectors and then one `(1,1,1,1)` vector. Its failing rationale claimed the answer omitted
the holiday exception even though that exception was explicitly present.

The evaluation contract also omitted evidence text and supplied only evidence IDs, so the Judge could
not independently assess evidence grounding. The reference labels were highly concentrated at 4-5,
which makes kappa unstable and does not test discrimination across quality levels.

## V2 requirement

Do not tune and re-claim performance on these seven cases. Build a development calibration set with
evidence text and deliberately sampled high, medium, and low quality outputs. Freeze a separate held-
out set before prompt changes. Keep exact safety, citation identity, cost, and latency outside the LLM
Judge regardless of v2 performance.
