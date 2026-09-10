# ADR 015: select Agentic policies independently

## Status

Accepted for Stage 3E.

## Decision

Select Router, Grader, and Rewriter independently under frozen quality and reliability gates. Missing
candidate evidence always retains the deterministic baseline. Rewriter selection requires trajectory
evidence and cannot inherit a Router or Grader win.

## Why

Component metrics expose where quality comes from and avoid paying LLM cost for a policy that does
not improve its own task. The conservative default also prevents a successful API call from being
misreported as a successful model experiment.

## Consequences

Stage 3 can end with a mixed policy stack. Initial thresholds are provisional because the seed is
small; independent labels, confidence intervals, token pricing, and repeated latency samples are
required before production selection.
