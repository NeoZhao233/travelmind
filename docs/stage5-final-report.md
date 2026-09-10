# Stage 5 final report: constraint-aware planning and repair

## Selected runtime

Stage 5 selects this planning path:

1. real Hybrid RRF retrieves grounded travel evidence;
2. a bounded narrative context and a provenance-linked candidate plane are constructed separately;
3. `explainable-greedy-v1` creates the itinerary using availability, budget, pace, directed travel,
   transfer buffers, and required/excluded places;
4. deterministic validation recomputes all hard constraints;
5. a two-attempt LangGraph loop repairs only supported local scopes;
6. unresolved constraints return safe failure.

DeepSeek is not selected for planning. Its safe-shortlist integration remains behind an interface for
future preference experiments, while the deterministic strategy is the runtime and outage fallback.

## Evidence by substage

| Substage | Evidence | Result |
| --- | --- | --- |
| 5A hard validation | 10 controlled cases | 1.000 exact violation match |
| 5B candidate planning | 5 controlled cases | 1.000 expected outcome and safe admission |
| 5C local repair | 7 controlled cases | 1.000 repair success, safe failure, preservation, outage recovery |
| 5D real end-to-end A/B | 5 non-blind pilot cases | Deterministic retained; DeepSeek lift 0.000 |

The final real A/B gave both variants 1.000 task success, validity, hard-constraint satisfaction,
and required-place coverage, plus 0.933 expected-place hit rate. DeepSeek added 4475 tokens and
about 877 ms mean latency without changing any final place sequence.

## Strong negative results retained

- A QA-tuned 768-token raw-text context cannot also be the planning candidate store; it reduced
  offline task success to 0.8 until the two-plane context split.
- A strict full-permutation output contract caused 0.8 LLM fallback because DeepSeek returned safe
  shortlists. The corrected shortlist contract reached zero fallback.
- Zero integration fallback is not sufficient for selection. The model still produced zero quality
  lift and remained more expensive.
- Provider-success/schema-failure calls consume real tokens; corrected diagnostics retain that cost.

## Claim boundary and next stage

All planning data beyond retrieval is controlled and the evaluation cases are small,
project-authored, and non-blind. Stage 5 proves component contracts, failure behavior, and an honest
selection process—not live itinerary quality. Stage 6 must expand and independently review the
dataset, calibrate judge metrics, establish regression gates, and build an error taxonomy before
resume-grade generalization claims.
