# TravelMind implementation roadmap

The roadmap is ordered to make every later technical claim measurable against an earlier baseline.
A stage is complete only when its code, tests, failure boundaries, ADRs, interview questions, and
reproducible evidence are present.

| Stage | Scope | Status | Exit gate |
| --- | --- | --- | --- |
| 0 | Python environment, package, CLI, minimal LangGraph, deterministic tests | Complete | Clean-environment bootstrap and verification pass |
| 1 | Travel schemas, source policy, typed facts, chunking, labeled retrieval seed | Complete | Corpus and labels validate; project and clean-room checks pass |
| 2 | BM25 baseline, dense retrieval, metadata filters, RRF, optional reranker | Complete at pilot level | Fixed-set Recall/MRR/NDCG plus latency and ablations are reproducible |
| 3 | LangGraph Agentic RAG: routing, query rewrite, evidence grading, bounded retry | Complete at pilot level | Mixed stack selected by repeated real candidate and component gates |
| 4 | Context engineering: budgets, evidence packing, compression, provenance | Complete at pilot level | Real answer A/B passes quality, citation, fallback, token, and latency gates |
| 5 | Constraint-aware itinerary planning and partial repair | Complete at pilot level | Real Hybrid RRF end-to-end A/B selects a safe planner under frozen gates |
| 6 | End-to-end evaluation and optimization loop | In progress (6C reference Judge rejected; human verification and v2 data pending) | Versioned dataset, calibrated judging, regression gates, error taxonomy |
| 7 | Production hardening: checkpoints, cache, observability, dependency fallbacks | Complete at pilot level | Outage drills expose degradation and preserve safety boundaries |
| 8 | Temporal RAG ingestion and index lifecycle | Complete at pilot level | Live-source changes cannot partially publish or silently bypass freshness policy |
| 9 | Interview release, evidence audit, and rehearsal | Complete | Claims are reproducible, explainable, and demonstrable under interview constraints |
| 10 | Complex official-PDF ingestion and retrieval | Paused after 10A | Page-grounded PDF knowledge improves governed retrieval without weakening safety |
| 11 | Runtime planning, tool observation, replanning, and causal failure analysis | Complete | Injected failures cause bounded retry/replan/safe-stop with auditable attribution |
| 12 | Evaluation expansion, no-answer admission, and fault-matrix re-test | Draft complete; human review blocked | Intent-isolated labels reviewed independently before metric promotion |

Stage 4 order: ~~4A typed baseline and privacy-safe trace~~; ~~4B deterministic budget and sweep~~;
~~4C coverage-aware evidence packing~~; ~~4D deduplication, conflict handling, and compression~~;
~~4E memory isolation~~; ~~4F final evidence and real DeepSeek answer ablation~~.

Stage 5 order: ~~5A typed hard constraints and deterministic validation~~; ~~5B explainable candidate
construction and travel-time feasibility~~; ~~5C bounded partial repair~~; ~~5D end-to-end scenario
and real-model A/B~~.

Stage 6 order: ~~6A versioned governance manifest, split integrity, and review provenance~~;
~~6B deterministic split metrics and layered error taxonomy~~; 6C human-calibrated LLM-as-Judge
(v1 reference-only run rejected; human verification and evidence-aware v2 data pending);
~~6D frozen regression gates and optimization experiments~~. The current test partition is frozen but
project-authored, so independent review remains an exit-gate requirement rather than a completed claim.

Stage 7 order: ~~7A privacy-safe structured telemetry and observability outage drills~~; ~~7B bounded
timeouts, circuit breaker, and cache/degradation policy~~; ~~7C logical checkpoint/resume, strict
serialization, and idempotency~~; ~~7C.2 local durable checkpointer and receipts~~; ~~7D SLO and
multi-dependency outage drills~~.

Stage 8 order: ~~8A immutable snapshots, isolated validation, atomic index promotion, and rollback~~;
~~8B conditional HTTP fetching, bounded retries, and source-specific freshness~~; ~~8C typed parser
quarantine, conflict reconciliation, and incremental-index evaluation~~.

Stage 9 order: ~~9A final architecture, pinned release evidence, automated audit, and one-command
offline demo~~; ~~9B resume bullets and project narrative~~; 9C interview question bank,
architecture rehearsal, and timed demo script.

Stage 10 order: ~~10A governed PDF registry, bounded acquisition, payload admission, and immutable
snapshots~~; 10B text/layout/OCR parser routing and page provenance; 10C hierarchical chunking and
Hybrid RAG integration; 10D PDF retrieval, citation, failure, and incremental-value-upgrade gates.

Stage 11 order: ~~11A explicit versioned execution plan, typed tool observations, and bounded
Plan-Act-Observe-Replan runtime~~; ~~11B machine-checkable groundedness and layered retrieval/tool/
generation/validation/orchestration attribution~~; ~~11C controlled failure corpus, recovery metrics,
and frozen gates~~; ~~11C.2 multi-step mid-flight replan with completed-observation reuse~~;
~~11C.3 optional real DeepSeek replanner candidate and deterministic fallback A/B~~; ~~11D
interview narrative, release audit, and timed failure demo~~. Stage 11 is complete; Stage 10B–10D
remain available as the next document-ingestion track.

Stage 12 order: ~~12A expand retrieval evaluation to 105 queries/35 intent clusters with split
isolation and no-answer cases~~; ~~12B rerun BM25, Dense, Hybrid, and Reranker with cluster-level
uncertainty~~; ~~12C expand runtime faults to 34 exact contracts~~; ~~12D add a development-tuned
answerability admission candidate~~; 12E independent human label review and release promotion.

## Stage 2 implementation order

1. ~~Add a retrieval evaluation runner and metric contracts before advanced retrieval.~~
2. ~~Establish a lexical BM25 baseline and hard-filter behavior.~~
3. ~~Add a dense adapter and record embedding model/version metadata.~~
4. ~~Compare direct, lexical, and dense runs on the same dataset.~~
5. ~~Add RRF fusion with single-channel degradation; defer tuning until a development split.~~
6. ~~Evaluate reranking; retain its adapter but reject it as default because its measured result does not justify latency.~~
7. ~~Inject single-channel and reranker exception/timeout failures and verify degraded modes.~~

The original 15-query set remains a pipeline seed. Stage 12 expands it to 105 queries/35 intent
clusters with split isolation and abstention cases. Independent human review remains required before
the new metric can become a resume-grade claim.

## Stage 3 implementation order

1. ~~Build the bounded LangGraph control plane with injected Router, Grader, Rewriter, and Retriever.~~
2. ~~Add Multi-Query RRF with bounded fanout and partial-failure behavior.~~
3. ~~Separate retrieval relevance labels from routing and evidence-sufficiency labels.~~
4. ~~Freeze a deterministic `rule-v1` policy baseline with development/test breakdowns.~~
5. ~~Add controlled trajectory cases for direct retrieval, successful rewrite recovery, exhausted
   retry, and dependency degradation.~~
6. ~~Evaluate Agentic control against one-shot control on task success, unsupported generation,
   retry success, and retrieval calls.~~
7. ~~Run an initial end-to-end Agentic versus Direct Hybrid RRF comparison, including real local
   latency.~~ Expand it with reviewed held-out recovery cases before quality claims.
8. ~~Add optional DeepSeek policy adapters, structured validation, telemetry, and deterministic
   fallbacks after freezing the comparison contract.~~
9. ~~Add component-level Stage 3E selection gates, run the real candidate with an explicitly
   configured API key, and retain only components that pass.~~
