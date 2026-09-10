# Stage 3B: policy evaluation foundation

## Outcome

Stage 3B introduces task-specific labels for two Agentic RAG decisions that retrieval metrics cannot
measure: query routing and evidence-set sufficiency. The first deterministic report is intentionally
frozen before optimization.

## Dataset contract

- Routing: 15 cases linked to the existing retrieval queries; 10 development and 5 test.
- Evidence grading: 11 explicit query/evidence-set cases; 6 development and 5 test.
- Every row has a stable case ID, rationale, annotator, review flag, and fixed split.
- The runner rejects duplicate IDs, unknown query/document references, or a missing split.
- Corpus and all related label files contribute to a SHA-256 experiment fingerprint.

All labels are `project_draft` and `reviewed=false`. The test split is useful for catching accidental
overfitting and evaluator bugs, but it is not blind or independently authored.

## Frozen `rule-v1` baseline

| Decision | Split | Cases | Primary metric |
| --- | ---: | ---: | ---: |
| Routing | development | 10 | accuracy 0.700 |
| Routing | test | 5 | accuracy 0.000 |
| Routing | all | 15 | accuracy 0.467 |
| Evidence sufficiency | development | 6 | accuracy 1.000, F1 1.000 |
| Evidence sufficiency | test | 5 | accuracy 0.600, F1 0.667 |
| Evidence sufficiency | all | 11 | accuracy 0.818, F1 0.857 |

The Grader's all-case required-aspect exact match is 0.727 and missing-aspect exact match is 0.818.
These numbers come from `evals/results/agentic_policy_rule_v1_seed.json` and must not be presented as
statistically significant model-quality claims.

## Error analysis

The Router missed unseen surface forms for known concepts, including “哪个门进/门出”, “联票全价”,
and time-of-day phrasing. It also lacked an explicit representation for location and attraction-type
filters, so several multi-constraint discovery requests collapsed into exact-fact or generic routes.

The Grader had the same root weakness. When a request's required aspect was not detected, trusted but
irrelevant evidence could be marked sufficient. This is more dangerous than a false negative because
it can allow unsupported planning. Recall of the `sufficient=true` class happened to be 1.0, but the
small set contains no basis for a safety claim.

## Why these metrics

- Router accuracy and a confusion table expose control-path errors.
- Grader precision/recall/F1 separate unsafe false positives from unnecessary retries.
- Required- and missing-aspect exact match diagnose whether a correct binary answer was reached for
  the right reason.
- Per-case reason codes make every aggregate number auditable.

## Reproduce

```bash
./scripts/bootstrap.sh
travelmind eval-agentic --root . --output evals/results/agentic_policy_rule_v1_seed.json
```

## Next gate

Do not optimize against these five observed test cases. Add independently reviewed cases, freeze a
new untouched test partition, and use only development cases for policy changes. In parallel, add
trajectory-level cases to measure rewrite recovery, retry exhaustion, unsupported-generation rate,
retrieval-call amplification, latency, and degraded dependency paths.
