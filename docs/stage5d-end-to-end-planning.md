# Stage 5D: end-to-end planning and real DeepSeek A/B

## Integrated path

Stage 5D connects the selected technical layers into one executable path:

```text
Hybrid RRF retrieval
  -> typed evidence/aspect enrichment
  -> 768-token refined-coverage narrative context
  -> provenance-linked structured candidate plane
  -> deterministic or DeepSeek-ranked candidate planning
  -> hard validation
  -> bounded local repair when needed
  -> valid itinerary or safe failure
```

The live evaluation uses the real local BM25 + BGE-small-zh + Qdrant + RRF retriever and the real
DeepSeek HTTP adapter. Opening hours, booking confirmation, prices, durations, and travel edges are
controlled fixtures, so this remains a pipeline pilot rather than a live travel product.

## Two-plane context correction

The first offline integration reused Stage 4's 768-token answer context as the only candidate source.
It packed two evidence documents per case and reduced deterministic task success to 0.8 because
multi-day planning candidates disappeared before scheduling.

The correction separates two responsibilities:

- narrative evidence plane: token-bounded raw text shown to the model;
- structured candidate plane: every retrieved place with typed fields and evidence provenance,
  consumed by deterministic feasibility code and the compact LLM ranking payload.

This is not permission to use unsupported candidates. Every candidate must still originate from a
retrieved place-linked evidence record. The split prevents a QA-tuned prompt budget from becoming an
accidental recall filter for multi-day planning. After the correction, deterministic task success
returned to 1.0 while mean narrative context remained about 492 estimated tokens.

## Planner variants

The deterministic variant uses `explainable-greedy-v1`. The DeepSeek variant does not own hard
times, arithmetic, booking, or route feasibility. It returns a soft-preference shortlist; unknown or
duplicate IDs are invalid, omitted known candidates are appended in original retrieval order, and
the deterministic scheduler materializes and validates the itinerary.

The selection gate was frozen before live calls:

- no regression in valid-plan rate, constraint satisfaction, or expected-place hit rate;
- at least 0.05 expected-place hit-rate lift;
- candidate fallback rate at most 0.10.

Expected-place precision was added later as an explicitly post-hoc diagnostic after observing that
recall alone can reward adding more places. It did not change the already-failed selection result.

## Real A/B and retained negative evidence

The strict-permutation v1 prompt produced valid provider responses but four of five outputs omitted
candidates. Its original report also undercounted failed-validation usage as zero. The diagnostic
rerun preserved actual usage: 0.8 fallback and 4443 provider tokens. All four failures had missing
known IDs and zero unknown IDs, showing that the model returned a shortlist rather than malformed
place identities.

The v2 contract accepted a safe shortlist and deterministically appended omitted candidates. This
removed fallback without weakening ID safety. A final v3 repetition added expected-place precision.

| Metric | Deterministic | DeepSeek-ranked |
| --- | ---: | ---: |
| Task success | 1.000 | 1.000 |
| Valid-plan rate | 1.000 | 1.000 |
| Constraint satisfaction | 1.000 | 1.000 |
| Required-place coverage | 1.000 | 1.000 |
| Expected-place hit rate | 0.933 | 0.933 |
| Post-hoc expected-place precision | 0.850 | 0.850 |
| Repair activation | 0.000 | 0.000 |
| Planner fallback | 0.000 | 0.000 |
| Provider tokens | 0 | 4475 |
| Mean successful provider latency | 0 | 877 ms |

Both variants produced the same final place sequence in every case. Expected-place lift was zero,
so the frozen gate failed and the deterministic planner remains selected. The DeepSeek adapter stays
available as an experimental component for a future dataset with genuinely ambiguous soft
preferences.

## Reproduce

Offline deterministic Hybrid RRF run:

```bash
travelmind eval-e2e-planning --root . --retriever hybrid --offline \
  --output evals/results/e2e_planning_hybrid_deterministic_v1.json
```

Real A/B, after setting `DEEPSEEK_API_KEY`:

```bash
travelmind eval-e2e-planning --root . --retriever hybrid --live-deepseek \
  --output evals/results/e2e_planning_deepseek_ab_v3_final.json
```

## Claim boundary

The five cases are project-authored, non-blind, and observed during interface and metric correction.
They support architecture, failure-analysis, and component-selection claims only. They do not prove
statistical significance, live route accuracy, real booking availability, or preference quality on
natural traffic.
