# Stage 6D: frozen regression and paid-component gates

## Outcome

The release decision is now executable rather than a manual reading of metrics. A versioned profile
pins the exact Stage 6 audit hash, governed dataset/manifest fingerprints, required splits, quality
floors, forbidden safety symptoms, fallback ceiling, and provider cost/latency ceilings.

The deterministic planner passed all 17 checks. The same frozen profile rejected the DeepSeek-ranked
planner on exactly one check: it used 895 provider tokens per case and about 877 ms mean provider
latency but produced 0.000 expected-place hit-rate lift. Paid candidates require at least 0.05 lift.

## Gate layers

1. **Comparability:** candidate dataset and governance hashes must match the baseline.
2. **Per-split quality:** task success, valid plans, hard constraints, required-place coverage, and
   expected-place hit rate cannot decrease on development or test.
3. **Safety symptoms:** pipeline, retrieval/context/candidate empty, hard-constraint, required-place,
   provider/schema, and exhausted-repair errors are forbidden.
4. **Reliability:** fallback rate must be at most 10%.
5. **Cost:** at most 1000 provider tokens per case and 1500 ms mean provider latency.
6. **Incremental value:** a component that consumes provider tokens must improve expected-place hit
   rate by at least 0.05 over the zero-token baseline.

Expected-place precision is not a frozen gate because it was introduced after the Stage 5 run and
the expected set is incomplete. Judge scores are also excluded until Stage 6C passes calibration.

## Why a file-backed profile

Thresholds stored in code are easy to change in the same pull request as a failing candidate. The
profile has its own identity and pins the immutable baseline report hash. Any changed baseline fails
closed until a deliberate new profile version is reviewed.

The current CLI exits with code 1 on rejection, so it can be placed directly in CI. Passing this
small pilot prevents known measured regressions; it does not prove general quality.

## Reproduction

```bash
travelmind check-regression-gate --root . --candidate-variant deterministic \
  --output evals/results/stage6d_regression_gate_deterministic_v1.json

travelmind check-regression-gate --root . --candidate-variant deepseek_ranked \
  --output evals/results/stage6d_regression_gate_deepseek_v1.json
```

The second command is expected to exit with status 1. Rejection is a successful test of the gate,
not a command failure to hide.
