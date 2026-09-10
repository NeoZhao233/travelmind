# Stage 4C: coverage-aware evidence packing

## Problem

Stage 4B admitted evidence in retrieval order. That is a strong relevance baseline, but it can spend
a tight context budget on several documents covering the same fact type. The clearest failure was
`beijing-multi-001`: two booking documents were admitted while the evidence covering opening hours,
free admission, no booking, and accessibility was omitted.

## Design

The selector infers requested aspects from the query and runtime hard filters. Candidate aspects
come from the corpus's typed `FactRecord` metadata. Evaluation relevance labels and
`expected_fact_types` are never selector inputs.

For each remaining candidate, the deterministic policy computes:

```text
utility = retrieval_priority + 10 * newly_covered_requested_aspects
```

Ties use aspect gain, retrieval priority, and original order. A bounded bonus preserves a relevance
signal instead of allowing any low-ranked, broadly tagged document to jump to the front. The chosen
order then passes through the unchanged Stage 4B cap, clip, mandatory-preservation, and output-reserve
logic.

If query-aspect inference or typed metadata has no coverage signal, every gain is zero and the
selector exactly falls back to retrieval priority.

## A/B results

| Budget | Metric | Priority packing | Coverage packing |
| ---: | --- | ---: | ---: |
| 768 | Mean relevant-document recall | 0.922 | 0.944 |
| 768 | Mean expected-aspect coverage | 0.967 | 1.000 |
| 768 | Multi-constraint relevant-document recall | 0.778 | 0.889 |
| 768 | Multi-constraint aspect coverage | 0.833 | 1.000 |

At the selected 768 envelope, one of 15 cases improves and zero regress; mean token use is identical
(511.3 for both paths). This supports selecting coverage-aware packing for the next ablation, but
the project-authored 15-query seed is not large enough for a production claim.

Aspect coverage is paired with document recall because a selector could otherwise obtain a high
coverage score from broadly tagged but irrelevant evidence.

## Failure boundaries

- Missing aspect metadata: retain retrieval order.
- Unknown query phrasing: infer `description` as a safe generic target and retain rank signal.
- Incorrect or over-broad tags: bounded coverage bonus limits promotion; relevance regression is a
  release gate.
- Mandatory overflow, tokenizer failure, and evidence overflow retain all Stage 4B behavior.
- Coverage trace records target names and reason codes, never request or evidence content.

## Reproduce

```bash
travelmind eval-context-coverage --root . \
  --output evals/results/context_coverage_768_seed.json

travelmind eval-context-coverage --root . \
  --max-context-tokens 768 \
  --reserved-output-tokens 192 \
  --safety-margin-tokens 64 \
  --output evals/results/context_coverage_768_seed.json
```
