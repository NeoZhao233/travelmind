# Stage 5A: deterministic hard-constraint validation

## Problem and ownership boundary

An LLM can propose a useful itinerary, but it is not the authority for arithmetic, interval
comparison, closure status, or booking confirmation. Stage 5A therefore treats generation as a
candidate-producing step and runs a typed deterministic validator before an itinerary can be
accepted.

The validator now covers:

- recomputed activity plus non-activity cost, claimed-total consistency, and budget;
- requested day count, required places, and excluded places;
- per-day time overlap using half-open intervals, so `10:00` end followed by `10:00` start is valid;
- activity evidence presence in strict mode;
- missing, unsourced, unknown, stale, and closed availability;
- full containment within a sourced operating window;
- confirmed booking when the availability record says booking is required.

All activity and operating-window timestamps must be timezone-aware. Availability is keyed by
`(place_id, service_date)`, and duplicate keys are rejected instead of resolving ambiguity by list
order.

## Why this stack

Pydantic validates data at the system boundary and produces explicit contracts. Plain Python owns
the hard checks because it is deterministic, fast, testable, and available when the model provider
is down. LangGraph remains the orchestration layer; it should route a failed validation to repair in
Stage 5C rather than embed business rules in graph edges or prompts.

Alternatives considered:

- prompt-only validation is flexible but nondeterministic and unsafe for arithmetic and closures;
- a generic constraint solver is attractive for global optimization, but adds modeling complexity
  before the candidate space and objective function exist;
- SQL constraints protect stored rows, but cannot express a whole proposed itinerary or provider
  freshness policy by themselves;
- naive datetimes are shorter to construct but make cross-timezone comparisons ambiguous.

## Fail-closed semantics

When strict validation receives no availability record, an unknown status, no source ID, or an
expired record, the affected activity is rejected with a distinct code. This preserves the
difference between “closed” and “we do not know.” The legacy graph can omit validation context for
its deterministic demo, but a Stage 5 production path must pass strict context.

The validator recomputes cost from line items and `non_activity_cost`; it does not trust the model's
claimed total. A mismatch and a budget breach can therefore be reported together. Error messages
contain place IDs and reason codes but no provider exception text.

## Controlled evaluation

Ten versioned, project-authored scenarios cover a valid plan, falsified total, overlap/exclusion,
missing/unknown/closed/stale availability, outside-hours scheduling, unconfirmed booking, and
missing activity evidence.

| Metric | Result |
| --- | ---: |
| Scenario count | 10 |
| Exact violation-set accuracy | 1.000 |
| Safety-case detection rate | 1.000 |
| Clean-case pass rate | 1.000 |

These figures prove behavior on controlled fixtures only. They do not prove live source freshness,
travel-time feasibility, natural-traffic coverage, or production availability.

## Reproduce

```bash
travelmind eval-planning-constraints --root . \
  --output evals/results/planning_constraints_controlled_v1.json
```

Stage 5B adds explainable candidate construction and travel-time feasibility. Stage 5C will use the
structured violations for bounded local repair rather than regenerate an entire itinerary.
