# Stage 5B: explainable candidate planning and travel feasibility

## Outcome

Stage 5B adds `explainable-greedy-v1`, a deterministic candidate scheduler that remains usable when
the LLM is unavailable. It converts retrieved place candidates, sourced availability, directed
travel-time edges, request constraints, and daily time windows into a typed itinerary plus an
auditable decision trace.

The baseline:

- schedules required places before optional places through an explicit bounded score bonus;
- limits daily activity count by relaxed, balanced, or intensive pace;
- finds the earliest activity slot fully contained in an operating window;
- reserves sourced inbound travel time and a configurable transfer buffer;
- verifies that the traveler can return to the daily origin before the day ends;
- enforces incremental budget before admitting a candidate;
- rejects unavailable, stale, unbooked, or route-unknown candidates;
- records selected score components and a reason code for every skipped candidate;
- sends the completed candidate back through the independent Stage 5A validator.

## Scoring contract

The current heuristic is intentionally simple and visible:

```text
utility = 100 * retrieval relevance
        + 20 * requested-interest matches
        - 0.2 * inbound travel minutes
        - 0.02 * estimated activity cost
        + 1000 when the place is required
```

The required bonus makes request compliance lexicographically stronger than normal utility within
the defined score ranges. Candidate ID provides a deterministic tie break. The exact weights are a
baseline configuration, not learned user preferences and not a claim of universal travel quality.

## Travel-time contract

Travel edges are directed and keyed by `(origin, destination, service_date)`. A known estimate must
include duration and evidence IDs. Missing, unknown, unsourced, or expired travel time is unusable.
The final validator independently checks origin-to-first, activity-to-activity, and final-to-origin
legs with the same minimum buffer.

This closes an important loophole: non-overlapping activities can still be impossible when transit
time is ignored.

## Why greedy first

A greedy scheduler is cheap, deterministic, explainable, and easy to failure-test. It establishes a
real baseline for later CP-SAT, beam search, or LLM planning. Introducing a solver first would hide
whether its extra modeling and operational cost actually improve constraint satisfaction or user
utility.

The known limitation is global optimality. Scheduling a required place early may prevent a
better combination later, and static heuristic weights cannot represent every user's trade-offs.
Stage 5D subsequently compared a DeepSeek candidate under the same hard-validation contract and
retained this baseline because the model produced no measured lift.

## Controlled evaluation

Five project-authored cases cover required-first scheduling, a missing inbound route, budget
pressure, unconfirmed booking, and missing return travel.

| Metric | Result |
| --- | ---: |
| Cases | 5 |
| Expected outcome exact match | 1.000 |
| Unsafe-activity-admission-free rate | 1.000 |
| Candidate decision-trace coverage | 1.000 |

These are deterministic contract fixtures, not natural-query quality evidence. Travel times are
static and do not model mode choice, traffic distributions, API outages, or uncertainty intervals.

## Reproduce

```bash
travelmind eval-candidate-planning --root . \
  --output evals/results/candidate_planning_controlled_v1.json
```

Stage 5C consumes typed violations and skip reasons to repair only the affected day or activity,
with a strict retry budget and safe failure when local repair cannot succeed.
