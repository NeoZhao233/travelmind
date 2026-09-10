# Stage 6A/6B: evaluation governance and deterministic error audit

## Outcome

Stage 6 now has a machine-checked boundary between a frozen experiment partition and a real blind
benchmark. The five Stage 5 cases are assigned to three development and two test cases, but all five
remain `project_authored`. The generated report therefore states `test_is_blind: false`; the split
prevents accidental tuning on every row but does not remove author bias.

The frozen Stage 5 DeepSeek A/B report was then re-audited by split and by deterministic symptom
code. Both planners still score 1.000 task success and hard-constraint satisfaction on both splits.
On the two-case test partition, expected-place hit rate is 0.833. The taxonomy also exposes two
`unexpected_selection` diagnostics and one `partial_expected_coverage` diagnostic per planner.
Those labels are not hidden behind the aggregate 1.000 task success.

## Why these components exist

| Component | Problem solved | Why not only documentation |
| --- | --- | --- |
| Dataset SHA-256 | Detect labels changed after an experiment | A README cannot stop stale report/data comparisons |
| Manifest and case coverage | Version split, authorship, and review state | Split metadata mixed into cases is easier to edit accidentally |
| Independent-review validator | Prevent unsupported benchmark claims | A string such as “reviewed” is otherwise unverifiable |
| Query/scenario leakage checks | Catch exact paraphrase/scenario overlap across splits | Unique case IDs alone do not prevent leakage |
| Layered issue codes | Preserve failure symptoms per case | One task-success average cannot guide optimization |
| Split metrics | Separate tuning evidence from frozen checks | Aggregate metrics can hide a held-out regression |

The manifest is deliberately separate from task labels: label content can remain immutable while
governance metadata evolves through review. The report records both dataset and manifest hashes.

## Reproduction

```bash
travelmind audit-e2e-evaluation --root . \
  --report evals/results/e2e_planning_deepseek_ab_v3_final.json \
  --manifest evals/datasets/e2e_planning_seed.manifest.json \
  --output evals/results/stage6ab_evaluation_audit_v1.json
```

The audit fails closed for a dataset hash mismatch, missing/unknown/duplicate case ID, empty
development or test split, cross-split normalized-query or scenario collision, and a false
independent-review claim.

## Interpretation boundary

- Five cases are not statistically stable and no confidence interval would make them representative.
- The expected-place set is incomplete. `unexpected_selection` means “not in this reference set,”
  not “objectively bad recommendation.”
- The taxonomy identifies observable symptoms, not proven root causes. Trace review is still needed.
- The old Stage 5 report predates per-row `candidate_count`, so that layer is marked unobserved rather
  than guessed.
- A resume-grade test set still needs new cases written or reviewed by another person and ideally
  hidden from the developer until the configuration is frozen.

## Next gate

Stage 6C should not ask an LLM judge to manufacture ground truth. First create a small human-scored
calibration set with rubric dimensions such as preference fit, itinerary coherence, evidence
support, and explanation usefulness. Then compare judge labels against humans, measure agreement
and bias, and keep deterministic hard-constraint metrics outside the judge.
