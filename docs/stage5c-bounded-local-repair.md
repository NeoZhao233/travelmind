# Stage 5C: bounded local itinerary repair

## Outcome

Stage 5C adds a dedicated LangGraph `validate -> repair -> revalidate` loop. It consumes the typed
violations from Stage 5A and changes the smallest supported scope instead of regenerating the whole
trip.

Repair scope is selected by violation type:

- `COST_TOTAL_MISMATCH`: recompute only the aggregate total;
- `EXCLUDED_PLACE_PRESENT`: remove the excluded activity;
- `BUDGET_EXCEEDED`: remove the highest-cost optional activities until the recomputed total fits;
- availability, booking, time, day-window, and travel violations: replan only affected days;
- `REQUIRED_PLACE_MISSING`: try the final day with the remaining candidate pool;
- unsupported structural failures such as invalid day numbering: stop without wasting retries.

Every repair is followed by the independent deterministic validator. A repair strategy cannot mark
its own output valid.

## LangGraph state and loop

The repair graph stores the current itinerary, constraints, operational context, candidates,
violations, attempts, modified days, sanitized dependency errors, and a compact trajectory. The
default retry budget is two.

```text
initialize -> validate --valid--------------------------> complete
                  |
             repairable + budget left
                  v
                repair -> validate
                  |
      unsupported or attempts exhausted
                  v
               safe failure
```

LangGraph makes the retry boundary, state transition, and trajectory visible and testable. A plain
loop could execute the same algorithm, but would need to recreate checkpoint and node-level
observability semantics as orchestration grows.

## Preservation and fallback semantics

Day replanning excludes places already scheduled on unaffected days and calculates the remaining
budget after their cost. It reuses Stage 5B's sourced availability, directed travel edges, transfer
buffer, and deterministic scoring. A day is recorded as modified only when its serialized typed
content actually changes; an unsuccessful repair attempt cannot inflate the modification count.

An injected primary repairer may later be an LLM or solver. Exception or malformed execution falls
back to `DeterministicDayRepairer`; only exception type and component name enter state. If both paths
fail, attempts remain bounded and the original invalidity is retained rather than published.

## Controlled evaluation

Seven project-authored cases cover no-op validation, total recomputation, budget repair, one-day
closure repair in a two-day trip, bounded impossible repair, immediate unsupported failure, and a
primary-repairer outage.

| Metric | Result |
| --- | ---: |
| Cases | 7 |
| Expected outcome exact match | 1.000 |
| Repairable-case success rate | 1.000 |
| Safe-failure accuracy | 1.000 |
| Unaffected-day preservation | 1.000 |
| Primary-repairer outage recovery | 1.000 |
| Mean repair attempts | 0.857 |

These are controlled fixtures. The evaluation does not yet compare an LLM repairer, prove semantic
trip quality, or cover concurrent checkpoint recovery.

## Reproduce

```bash
travelmind eval-itinerary-repair --root . \
  --output evals/results/itinerary_repair_controlled_v1.json
```

Stage 5D subsequently evaluated the complete retrieval, context, candidate planning, validation,
and repair path, then ran a real DeepSeek candidate against the deterministic fallback.
