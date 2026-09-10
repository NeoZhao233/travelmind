# Stage 11: agentic runtime and transparent failure handling

## Why this stage exists

Before Stage 11, TravelMind was best described as an evaluated RAG and constraint-planning pipeline
with two bounded feedback loops: retrieval query rewriting and itinerary repair. It was not yet a
general runtime that could observe a failed external action and revise the remaining plan. Stage 11
closes that claim gap without deleting the stable baseline.

## Runtime contract

The new graph follows:

`Plan -> select ready step -> Act -> Observe -> retry | Replan | Generate -> Validate -> finish | Replan`

An execution plan is data, not an implicit graph path. Revision 1 records the original strategy. A
permanent tool failure or invalid tool response becomes a typed failure observation; the planner is
then called with the previous plan, all observations, and failure attribution, and must return
revision 2. A timeout may retry the same step within its attempt budget and is not mislabeled as a
replan.

Three independent bounds prevent open-ended autonomy:

- per-step tool attempts;
- total plan revisions;
- total tool calls across revisions.

Exhaustion produces a safe failure rather than an unsupported itinerary.

## What “hallucination detection” means here

The deterministic validator checks claims that software can actually establish:

- every activity cites evidence;
- every cited ID exists in retrieved evidence or a successful tool observation;
- every place ID exists in an admissible evidence record;
- costs and hard constraints are recomputed instead of trusted from generated text;
- tool failures and invalid response schemas cannot become successful evidence.

This detects fabricated citations, fabricated entities, missing provenance, and deterministic
constraint violations. It does **not** prove that every natural-language sentence is semantically
entailed. Semantic claim decomposition plus an evidence-aware judge may be evaluated later, but must
remain a secondary signal rather than being presented as certainty.

## Failure attribution rules

| Observed boundary | Primary layer | Example reason |
| --- | --- | --- |
| Retrieval tool fails or returns an unusable retrieval result | retrieval | `TRANSIENT_ERROR`, `INVALID_OUTPUT` |
| Availability/booking/route tool fails | tool | `PERMANENT_ERROR` |
| Planner throws, returns no itinerary, or invents IDs | generation | `GENERATION_FAILED`, `UNSUPPORTED_OUTPUT` |
| Sourced itinerary violates recomputed constraints | validation | `CONSTRAINT_VIOLATION` |
| Invalid plan DAG or execution budget exhaustion | orchestration | `PLAN_CREATION_FAILED`, `TOOL_CALL_BUDGET_EXHAUSTED` |

The runtime records sanitized exception **types**, never exception messages. When one symptom has
multiple plausible contributors, the primary boundary is retained with contributing codes; the
report must not claim a uniquely proven root cause.

## Current evidence

Focused tests cover timeout retry without replan, permanent failure with revision 2,
invalid response separation, replan-budget safe stop, retrieval-layer attribution, invalid plan
dependencies, fabricated citations/entities, and successful live-observation provenance.

The first four-case controlled comparison reports recoverable completion of `33.3%` for a fixed-plan
baseline and `100%` for the replanning candidate. Expected replan behavior, failure-layer attribution,
and unrecoverable safe stop are each `100%`; mean tool calls are `2.0`. These are harness results on
project-authored fault injection—not live-provider reliability or a statistically general claim.
Independent review, more failure combinations, and real-tool tests remain required before selecting
this runtime as the default production path.

## Multi-step mid-flight replanning

The Stage 11C.2 scenario is longer than a single failing call. Revision 1 executes:

`candidate search -> primary availability -> primary booking -> primary travel time`

If booking or travel time fails after earlier steps succeeded, revision 2 does not repeat candidate
retrieval. It receives the complete observation history and executes only:

`fallback availability -> fallback travel time`

The final itinerary is generated from successful observations across both revisions. Four controlled
cases cover a healthy path, booking failure, primary-route failure, and failure of both routes. The
fixed-plan baseline recovers from `0%` of the two recoverable mid-flight failures; the replanning
candidate recovers from `100%`. Candidate retrieval runs once in every revised case, and dual-route
failure safely produces no itinerary. These rates are deterministic fixtures, not production claims.
