# ADR 023: establish an explainable greedy planner before adding a solver

## Status

Accepted for Stage 5B.

## Decision

Use a deterministic greedy scheduler as the first candidate-generation baseline. Score only
feasible candidates using explicit relevance, interest, travel, cost, and required-place
components. Keep travel facts sourced, directed, dated, and independently revalidated.

## Alternatives

- LLM-only planning: stronger natural-language priors, but nondeterministic and unsafe as the sole
  feasibility mechanism.
- CP-SAT/MILP: can optimize globally, but needs a trustworthy candidate graph and defensible
  objective weights; evaluate it later against this baseline.
- nearest-neighbor routing only: efficient geographically, but can ignore relevance, interests,
  cost, opening hours, and required places.
- undirected travel matrix: smaller, but incorrect when routes and congestion differ by direction.

## Consequences

The system gains an outage-safe planner, deterministic tie breaking, and a complete candidate
decision trace. It does not guarantee a global optimum. Static point travel estimates and manually
chosen weights remain explicit limitations and future ablation targets.
