# Stage 6C: human-calibrated LLM-as-Judge

## Current status

The calibration infrastructure and seven-item blind annotation packet are implemented. All seven
items now have Codex-assisted reference scores, explicitly marked `ai_assisted_unverified`. They may
support a cross-model diagnostic, but cannot pass the human-calibrated Judge selection gate until a
person reviews them and changes provenance to `human_verified`.

The real 21-call reference run is complete and Judge v1 is rejected. Provider/schema fallback was
zero and repeat consistency was 0.857, but every dimension missed the within-one agreement gate and
all weighted-kappa values were below threshold. See `stage6c-reference-judge-result.md`.

## Rubric v1

Score each dimension independently from 1 to 5. Use the response, its claim/citation structure, the
question, and whether abstention is expected. Do not reward writing style for factual correctness.

| Dimension | 1 | 3 | 5 |
| --- | --- | --- | --- |
| Answer correctness | Contradicts or misses the request | Main answer is useful but incomplete or slightly imprecise | Fully answers the request without material error |
| Evidence grounding | Important claims lack or misuse evidence IDs | Most important claims are supported, with minor granularity issues | Every material factual claim is traceably supported |
| Clarity/actionability | Confusing or unusable | Understandable but needs interpretation | Concise, specific, and directly usable for planning |
| Uncertainty calibration | Invents certainty or abstains despite sufficient evidence | Minor over/under-confidence | Answers when supported and clearly abstains/qualifies when unsupported |

Scores 2 and 4 mean the quality lies between the adjacent anchors. `annotation_notes` should record
ambiguous references or rubric disagreements, not hidden reasoning.

## Judge contract

The Judge receives no pipeline variant or model identity. It returns four bounded integer scores,
machine-readable reason codes, and a short auditable evidence summary. It is called three times at
temperature zero. Repeated scores are aggregated once per candidate before comparison with human
labels; repeats do not inflate the calibration sample size.

The predeclared acceptance gate requires:

- provider/schema fallback rate at most 5%;
- exact repeated-score consistency on at least 80% of candidates;
- per-dimension mean absolute error at most 0.75;
- per-dimension within-one agreement at least 90%;
- per-dimension quadratic-weighted Cohen's kappa at least 0.60.

Failure rejects the Judge as a release metric. It does not block deterministic evaluation.

## Why these metrics

- MAE shows score distance and is easy to explain.
- Within-one agreement tolerates adjacent rubric ambiguity.
- Weighted kappa accounts for chance agreement and penalizes large ordinal disagreements more.
- Mean bias reveals a systematically generous or harsh Judge even when agreement looks acceptable.
- Repeat consistency detects nondeterminism hidden by an average.

Kappa can be unstable on seven items or degenerate when human scores lack variation. This packet
validates workflow and exposes obvious disagreement; it is not enough for a production judge claim.

## Workflow

```bash
travelmind prepare-judge-calibration --root .
# Human reviews evals/annotations/judge_calibration_seed_v1.json
# Then set label_provenance to human_verified
travelmind eval-judge-calibration --root . --repeats 3 \
  --output evals/results/stage6c_deepseek_judge_calibration_v1.json
```

The second command needs `DEEPSEEK_API_KEY`. Missing annotations stop execution before the API call,
so incomplete labeling cannot spend tokens or generate a misleading partial calibration report.

## What remains

1. One human annotator reviews all seven AI-assisted reference labels.
2. Preferably, an independent second annotator scores a clean copy.
3. Measure human-human agreement before human-Judge agreement.
4. Resolve rubric disputes without editing system outputs.
5. Run the real Judge and retain negative results if the gate fails.

Hard constraints, citation identity, fallback, latency, token cost, and schema validity remain
deterministic metrics. LLM-as-Judge is only for qualities that cannot be adequately captured by exact
matching.
