# Stage 13: Agent Harness, MCP, and Redis

## Goal

Stage 13 reframes TravelMind as an Agent Harness whose retrieval system is one governed tool rather
than the whole application. The harness owns termination, budgets, tool policy, context, persistence,
failure attribution, and evaluation. Hybrid RAG remains the knowledge path behind that boundary.

## Harness boundary

Every tool has harness-owned metadata declaring whether it is read-only, idempotent, cacheable, and
eligible for local fallback. Validation rejects caching or fallback for mutating/non-idempotent tools.
The model cannot modify this policy through tool arguments.

The governed registry uses an explicit allowlist. It falls back only on transport-level timeout or
connection errors and only for tools whose policy permits it. A remote tool's typed business failure
is returned to the Runtime and may trigger retry or replan; it is not hidden by a local fallback.

## MCP

The official MCP Python SDK v2 exposes four structured tools:

- `candidate_search`;
- `availability`;
- `booking` (read-only requirement check, not reservation creation);
- `travel_time`.

The server also exposes `travelmind://harness/tool-policy` so a host can inspect non-secret cache and
side-effect policy. Tool exceptions are converted into typed, sanitized transient or permanent
outcomes. Tests use the official in-process MCP transport, which still performs discovery, schema
validation, and protocol calls without introducing network nondeterminism.

## Redis

Redis is optional and does not replace Qdrant:

- `RedisToolCache` applies canonical SHA-256 keys and per-tool TTLs;
- only successful, explicitly cacheable read operations are stored;
- cache read/write failure is best-effort and does not become a domain-tool outage;
- `RedisSaver` is available as a shared LangGraph Checkpoint backend;
- Memory, SQLite, and Redis are selected explicitly at startup;
- Checkpoint failure is fail-closed. The process never switches state stores mid-run because that
  could fork execution history and repeat side effects.

`deploy/compose.stage13.yml` and `travelmind eval-redis-backend` provide a real Redis cache and
checkpoint probe. The current workstation's Docker application is incomplete, so no live Redis
result is committed yet. Redis must not receive a resume reliability number until this probe passes.

## Controlled harness experiment

`evals/results/stage13_harness_v1.json` records six deterministic checks:

| Contract | Result |
| --- | ---: |
| Official in-process MCP path completes | pass |
| MCP transport failure uses allowed local read fallback | pass |
| Remote business failure remains visible and causes replan | pass |
| MCP and local path failure stops without an itinerary | pass |
| Successful cacheable read is reused | pass |
| Redis cache outage is bypassed without losing the tool | pass |

All six checks pass. The reported cache hit rate is `0.5` because the fixed experiment makes one miss
and one hit. This is a contract fixture, not a traffic-distribution estimate. In-process MCP latency
and fault-injected Redis behavior are not network or production SLO evidence.

## Reproduction

```bash
./scripts/bootstrap.sh --extra dense --extra checkpoint --extra redis
travelmind eval-harness --root . \
  --output evals/results/my_stage13_harness.json

docker compose -f deploy/compose.stage13.yml up -d
travelmind eval-redis-backend \
  --output evals/results/my_stage13_redis.json
docker compose -f deploy/compose.stage13.yml down
```

## Interview boundary

The accurate claim is that TravelMind implements and tests a governed MCP tool boundary plus optional
Redis cache/checkpoint adapters. It does not prove remote MCP availability, Redis cluster failover,
concurrent checkpoint throughput, or safe execution of real booking side effects.
