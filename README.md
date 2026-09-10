# TravelMind

TravelMind is an evaluation-first, constraint-aware travel planning agent. The project focuses
on LangGraph orchestration, agentic hybrid RAG, context engineering, deterministic itinerary
validation, and reproducible evaluation rather than frontend work.

## Current milestone

Stage 0 (reproducible engineering baseline), Stage 1 (evidence/evaluation data foundation), Stage
2A (BM25 baseline), Stage 2B (Chinese dense baseline), Stage 2C (parallel RRF hybrid), and Stage 2D
(optional cross-encoder ablation) are complete. See
`docs/stage0-engineering-baseline.md`, `docs/stage1-data-foundation.md`,
`docs/stage2a-bm25-baseline.md`, `docs/stage2b-dense-retrieval.md`, and
`docs/stage2c-hybrid-rrf.md`, and `docs/stage2d-reranker-ablation.md` for their contracts,
limitations, and acceptance evidence. The reranker regressed quality and latency, so Hybrid RRF
remains the default. Stage 3A's deterministic Agentic RAG control plane is also complete. Stage 3B
has added separate draft labels and a fixed development/test policy baseline. Stage 3C's controlled
trajectory comparison and the Stage 3C.2 live Hybrid RRF comparison are complete. The live seed
showed no Agentic quality lift. Stage 3D/3E are complete at pilot level after a real DeepSeek A/B:
the LLM Router passed the gate, while deterministic Grader and Rewriter remain selected.
Stage 4 is complete at pilot level. The selected 768-token refined-coverage pipeline combines typed
context, budgeting, coverage-aware packing, deterministic evidence refinement, and scoped memory. A
real DeepSeek answer A/B improved task success and citation metrics to 1.000 on seven seed cases while
reducing total tokens by 45.3%; this is pilot evidence, not a production-quality claim.
Stage 5A is complete: a typed deterministic validator now recomputes cost and checks day count,
required/excluded places, overlaps, evidence, opening status/hours, freshness, and booking state.
All ten controlled scenarios pass exact expected-violation matching.
Stage 5B is also complete: the provider-independent `explainable-greedy-v1` baseline now schedules
required and optional candidates using sourced directed travel times, transfer buffers, opening
windows, booking, budget, pace, and an auditable utility score. Five controlled planning scenarios
pass; this is not a claim of global optimality or live traffic quality.
Stage 5C is complete: a dedicated LangGraph loop performs at most two local repairs, preserves
unaffected days, falls back to deterministic repair on primary-strategy failure, and safely retains
unresolved violations. Seven controlled repair scenarios pass their exact outcome gates.
Stage 5D completes the pilot end-to-end path with real local Hybrid RRF and a real DeepSeek planner
A/B. The safe-shortlist v2 removed integration fallback, but DeepSeek produced zero quality lift,
added 4475 tokens and about 877 ms per call, so the deterministic planner remains selected.
Stage 6A/6B are complete at pilot level: a hashed governance manifest freezes a 3/2 split, checks
review provenance and cross-split leakage, and adds per-split metrics plus layered error codes. The
test labels are explicitly project-authored and non-blind; Stage 6C calibration and independent
review are still pending.
Stage 6C has a 21-call DeepSeek reference-only run against seven AI-assisted labels. Every call was
schema-valid and repeat consistency reached 0.857, but agreement and kappa gates failed. Judge v1 is
rejected; evidence-aware stratified v2 data and human verification are required before any
human-calibrated claim.
Stage 6D is complete at pilot level: a hash-pinned release profile applies 17 comparability, quality,
safety, fallback, cost, latency, and incremental-value checks. The deterministic baseline passes;
the paid DeepSeek ranker is rejected because its expected-place lift is zero.
Stage 7A is complete: the planning path emits correlated, versioned, allowlisted telemetry without
queries, prompts, evidence, or exception messages. Sink outage preserves business completion and is
reported as `telemetry_degraded`; the three-scenario redaction/fallback drill passed all contracts.
Stage 7B adds a thread-safe closed/open/half-open retrieval circuit breaker and a hashed-key cache.
Fresh cache can cover transient faults; bounded stale fallback allows only explicit static evidence,
while stale dynamic or expired evidence fails closed. All eight controlled transition checks pass.
Stage 7C adds injected LangGraph checkpointing, strict serialization allowlists, scoped idempotency
receipts, and checkpoint-outage failure behavior. Logical resume avoids a repeated Planner call, but
the in-memory pilot alone is explicitly not process-durable. Stage 7C.2 adds the optional official
SQLite saver and durable receipt store: independent Python processes resumed at `validate` and
replayed the Planner receipt with zero repeated Planner calls.
Stage 7D completes the production-hardening pilot with an explicit synthetic pre-release SLO gate.
A simultaneous retrieval/model/telemetry outage completed through visible deterministic fallbacks;
loss of both retrieval paths failed safely without an itinerary. These fixture results are not
presented as a production availability or latency SLO.
Stage 8A starts the Temporal RAG ingestion track with content-addressed raw snapshots, isolated index
builds, validation quarantine, atomic active-version promotion, and pointer rollback. The local drill
passed all seven lifecycle checks; remote object-store/vector-database semantics remain future work.
Stage 8B adds conditional HTTP validation, bounded transient retry, and typed freshness policy.
Dynamic stale data fails closed; explicitly static data has a finite fallback window. The controlled
transport drill passed all eight checks and is not presented as a live-source availability claim.
Stage 8C completes the Temporal RAG ingestion pilot with a typed parser boundary, sanitized parse
quarantine, semantic-key conflict resolution, unresolved-fact suppression, and atomic incremental
fact updates. The controlled drill passed all eight contracts; the index remains an in-memory
reference rather than a remote vector-database concurrency claim.

Stage 9A freezes the interview release: the final runtime/data architecture, evidence-backed claim
boundaries, a SHA-256 release manifest, a 33-check automated audit, and a one-command offline demo.
Run `./scripts/interview-demo.sh` to exercise the agent plus its outage, publishing, ingestion, and
release-evidence gates without spending provider tokens.
Stage 9B packages the frozen evidence into a full and compact Chinese resume entry plus 30-second,
2-minute, and 5-minute interview narratives. Claim-to-evidence mappings and statements to avoid are
recorded in `docs/interview/resume-project.md` and `docs/interview/project-narrative.md`.
Stage 10A begins complex-document ingestion with a governed registry of four official Beijing PDF
sources. Exact-host HTTPS fetching, bounded retries and size, MIME/magic/EOF checks, active-content
rejection, optional digest pinning, and immutable snapshots prevent bad or partial PDFs from reaching
an index. Raw third-party PDFs remain outside Git; parsing and retrieval claims begin in Stage 10B,
which is currently paused.

Stage 11 is complete. A separate LangGraph runtime now represents execution plans as
versioned data, records typed tool observations, retries only transient failures, replans after
permanent or schema failures, and stops safely under attempt/replan/call budgets. Deterministic
grounding checks reject fabricated citations and place IDs. In four controlled fault cases, the
fixed-plan baseline completed 33.3% of recoverable cases versus 100% for the replanning candidate;
these are project-authored injected cases, not production reliability evidence.

Stage 11C.2 extends this beyond one-step recovery. A four-step trajectory performs candidate search,
availability, booking, and travel-time checks. Mid-flight failures create revision 2, reuse the
completed candidate-search observation, and replace only downstream work with an alternative place.
Both recoverable intermediate failures complete; failure of both primary and fallback routes safely
returns no itinerary. These are four deterministic fixtures, not a live-provider claim.

Stage 11C.3 evaluates a real DeepSeek structured replanner behind tool schemas, place allowlists,
runtime-owned arguments, and deterministic fallback. The final run matched the deterministic
four-case contract with zero fallback, but produced zero measured lift, consumed 5725 tokens at about
1.08 seconds mean latency, and required argument normalization on 42.9% of calls. It failed the frozen
selection gates, so the deterministic runtime planner remains the default.

Stage 11D closes the agentic-runtime track with a separately pinned v2 architecture and release
manifest, seven additional semantic audit checks, updated resume/interview narratives, and an offline
failure demo. The demo reruns multi-step failure injection without a provider key; the committed live
DeepSeek report is audited rather than replayed, so an interview rehearsal spends no API tokens.

The repository currently contains a runnable, dependency-injected LangGraph backbone:

1. initialize request state;
2. build retrieval queries;
3. retrieve and grade evidence;
4. rewrite and retry when evidence is insufficient;
5. generate a structured itinerary;
6. validate deterministic constraints;
7. return a safe fallback after bounded retries.

The Stage 11 candidate adds a second, explicitly agentic control path:

1. create revision 1 of a typed execution plan;
2. execute the next dependency-ready tool step;
3. record a sanitized typed observation;
4. retry transient faults or create a new plan revision for structural failures;
5. expose successful tool observations as realtime evidence to itinerary generation;
6. validate provenance and constraints, then complete, replan, or stop safely.

The default demo uses deterministic adapters, so normal execution does not require an API key or model
download. Qdrant local dense retrieval, reranking, and DeepSeek policy/planning/Judge adapters were
measured behind interfaces. PostgreSQL, remote Qdrant, and remote telemetry remain production targets;
evaluated model components are selected only when their gates pass.

Stage 1 adds a schema-validated Beijing seed corpus, typed facts, deterministic structure-aware
chunking, and 15 reviewed retrieval queries. These are dataset counts, not model-quality claims.

## Setup

```bash
./scripts/bootstrap.sh
source .venv/bin/activate
travelmind demo "带父母去北京三天，预算3000元，喜欢历史文化"
travelmind agentic-demo "周一带父母去故宫，需要门票和预约信息"
travelmind eval-agentic --root . --output evals/results/agentic_policy_rule_v1_seed.json
travelmind eval-trajectory --root . --output evals/results/agentic_trajectory_rule_v1_seed.json
travelmind eval-live-agentic --root . --local-files-only \
  --output evals/results/live_hybrid_agentic_rule_v1_seed.json
travelmind eval-runtime-replanning --root . \
  --output evals/results/stage11_runtime_replanning_v1.json
travelmind eval-runtime-multistep --root . \
  --output evals/results/stage11_runtime_multistep_v1.json
travelmind eval-deepseek-runtime --root . \
  --output evals/results/stage11_deepseek_runtime_v3_final.json
travelmind select-agentic-policies --root .
travelmind eval-context-sweep --root . \
  --output evals/results/context_budget_sweep_v1_seed.json
travelmind eval-context-coverage --root . \
  --output evals/results/context_coverage_768_seed.json
travelmind eval-context-refinement --root . \
  --output evals/results/context_refinement_controlled_v1_seed.json
travelmind eval-memory --output evals/results/memory_isolation_controlled_v1.json
travelmind eval-context-answers --root . \
  --output evals/results/stage4_deepseek_answer_ablation_v4_final.json
travelmind eval-planning-constraints --root . \
  --output evals/results/planning_constraints_controlled_v1.json
travelmind eval-candidate-planning --root . \
  --output evals/results/candidate_planning_controlled_v1.json
travelmind eval-itinerary-repair --root . \
  --output evals/results/itinerary_repair_controlled_v1.json
travelmind eval-e2e-planning --root . --retriever hybrid --live-deepseek \
  --output evals/results/e2e_planning_deepseek_ab_v3_final.json
travelmind audit-e2e-evaluation --root . \
  --output evals/results/stage6ab_evaluation_audit_v1.json
travelmind prepare-judge-calibration --root .
travelmind check-regression-gate --root . --candidate-variant deterministic
travelmind eval-observability --root . \
  --output evals/results/stage7a_observability_drill_v1.json
travelmind eval-retrieval-resilience --root . \
  --output evals/results/stage7b_retrieval_resilience_v1.json
LANGGRAPH_STRICT_MSGPACK=true travelmind eval-checkpointing --root . \
  --output evals/results/stage7c_checkpoint_idempotency_v1.json
LANGGRAPH_STRICT_MSGPACK=true travelmind eval-durable-checkpointing --root . \
  --output evals/results/stage7c2_durable_checkpoint_v1.json
travelmind eval-slo-outages --root . \
  --output evals/results/stage7d_slo_outage_v1.json
travelmind eval-index-publishing --root . \
  --output evals/results/stage8a_index_publish_v1.json
travelmind eval-source-fetching --root . \
  --output evals/results/stage8b_source_fetch_v1.json
travelmind eval-incremental-ingestion --root . \
  --output evals/results/stage8c_incremental_ingestion_v1.json
travelmind validate-data --root .
travelmind eval-retrieval --root .
./scripts/verify.sh
```

To run the optional Chinese dense baseline:

```bash
./scripts/bootstrap.sh --extra dense
travelmind eval-retrieval --root . --retriever dense
travelmind eval-retrieval --root . --retriever hybrid --local-files-only
./scripts/verify-dense.sh
```

To install the local durable SQLite checkpoint adapter:

```bash
./scripts/bootstrap.sh --extra checkpoint
```

The optional reranker is an ablation, not the default path, and requires an additional model of
about 1.04GB:

```bash
travelmind eval-retrieval --root . --retriever reranked --local-files-only
./scripts/verify-reranker.sh
```

To install the optional API and OpenAI-compatible SDK integrations:

```bash
./scripts/bootstrap.sh --extra api --extra openai
```

The DeepSeek adapter uses core `httpx` and does not require the `openai` extra. A live candidate needs
`DEEPSEEK_API_KEY`; absence of the variable retains deterministic policies and produces no model
quality claim.

`bootstrap.sh` uses a non-editable project install because this macOS environment reapplies the
`hidden` filesystem flag to editable-install `.pth` files between processes. Run the bootstrap
again after changing source code and before verification. This is less convenient than an editable
install, but it makes package imports and CLI cold starts reproducible in this environment.

## Engineering rule

Every non-trivial component must ship with:

- a problem statement and explicit contract;
- alternatives and trade-offs in an ADR;
- known failure modes, fallback behavior, and recovery boundaries;
- deterministic tests where possible;
- at least one relevant failure-injection or degradation test;
- an evaluation or ablation plan;
- likely interview questions and evidence-backed answers.

See `docs/architecture.md`, `docs/reliability.md`, `docs/adr/`, and
`docs/interview/questions.md`. The staged delivery and exit gates are in `docs/roadmap.md`.
