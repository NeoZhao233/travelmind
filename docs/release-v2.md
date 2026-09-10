# TravelMind v2 interview release evidence

TravelMind v2 keeps every v1 retrieval, context, reliability, and ingestion claim, then closes the
agentic-control gap with a separate Plan–Act–Observe–Replan runtime. The v1 manifest remains frozen;
v2 pins the additional architecture and runtime reports.

## Added evidence

| Claim | Evidence | Result |
| --- | --- | --- |
| Multi-step runtime contract | Four controlled cases | 4/4 contract checks passed |
| Mid-flight recovery | Booking and travel failures | Agentic 2/2; fixed baseline 0/2 |
| Observation reuse | Replanned recoverable cases | Candidate search called once in each case |
| Unsafe-path behavior | Unrecoverable booking failure | Safe stop, no unsupported itinerary |
| Real DeepSeek runtime A/B | Seven planning/replanning calls | Zero contract lift; 42.9% normalized; candidate rejected |

## Selection boundary

The agentic runtime itself is selected because it adds measured intermediate-failure recovery. The
DeepSeek policy is not selected because it does not improve the deterministic contract, exceeds the
25% argument-normalization gate, consumes 5,725 tokens, and adds about 1.08 seconds mean candidate
latency. Deterministic termination, provenance checks, allowlists, and fallback remain in control.

## Reproduction

```bash
travelmind eval-runtime-multistep --root .
travelmind release-audit --root . --manifest release/travelmind-v2.json
./scripts/interview-demo.sh
```

The offline demo does not call DeepSeek. The committed DeepSeek report records the already completed
live experiment, so interview rehearsal remains reproducible without spending API tokens.
