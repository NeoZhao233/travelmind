# TravelMind v3 interview release evidence

TravelMind v3 adds a governed Agent Harness boundary around the existing Plan-Act-Observe-Replan
Runtime. Hybrid RAG remains the evidence tool; MCP standardizes selected external tool interfaces;
Redis is an optional cache/checkpoint backend rather than a replacement for Qdrant or SQLite.

## Added evidence

| Claim | Evidence | Result |
| --- | --- | --- |
| Official MCP protocol path | Four structured in-process tools | Runtime completed without fallback |
| Transport-only fallback | MCP connection failure | Four read-only calls used local adapter and completed |
| Business failure visibility | Remote booking-rule failure | No hidden local fallback; Runtime replanned once |
| Dual-path behavior | MCP plus local adapter failure | Safe stop with no itinerary |
| Cache policy | One fixed miss followed by one hit | Successful read reused; fixed hit rate 0.5 |
| Cache outage behavior | Fault-injected Redis client | Original tool completed; no fabricated cache response |

## Selection boundary

The MCP boundary and harness-owned Tool Policy are selected. Redis code is selected as an optional
adapter, but no live Redis reliability claim is promoted because the current machine has no working
container engine. The committed Harness report explicitly labels Redis as fault-injected.

Historical v1 and v2 manifests are not rewritten when dependencies change. They audit their original
commits; v3 pins the current dependency files and Stage 13 evidence.

## Reproduction

```bash
travelmind eval-harness --root . \
  --output evals/results/my_stage13_harness.json
travelmind release-audit --root . --manifest release/travelmind-v3.json
```
