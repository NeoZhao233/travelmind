# Retrieval experiment results

Each JSON file is produced by `travelmind eval-retrieval`, contains the dataset fingerprint and full
configuration, and should be treated as immutable evidence for that run.

- `bm25_lexical_seed.json`: pure lexical ranking.
- `bm25_filtered_seed.json`: same BM25 index with currently supported metadata prefilters.
- `dense_bge_small_zh_v15_seed.json`: Qdrant local dense retrieval with the version-recorded Chinese
  BGE model and cached-artifact fingerprint.
- `hybrid_rrf_seed.json`: concurrent BM25 and dense retrieval fused at document level with RRF,
  including per-channel status and degradation diagnostics.
- `hybrid_bge_reranker_base_seed.json`: optional BGE cross-encoder ablation over fixed RRF
  candidates. It is retained as negative evidence and is not the default path.
- `agentic_policy_rule_v1_seed.json`: frozen `rule-v1` Router and evidence-Grader baseline on separately
  labeled development/test cases. Its weak held-out results are retained as optimization evidence,
  not hidden or overwritten.
- `agentic_trajectory_rule_v1_seed.json`: controlled Direct-versus-Agentic trajectory comparison;
  scripted real-document returns isolate rewrite/retry behavior from ranking variance.
- `live_hybrid_agentic_rule_v1_seed.json`: Direct-versus-Agentic run over the actual local Hybrid
  RRF stack; it records no quality lift and preserves the measured call/latency overhead.
- `deepseek_policy_candidate.json`: v1 negative result with thinking enabled and 76.9% fallback.
- `deepseek_policy_candidate_nonthinking_v2.json`: non-thinking v2; all calls returned valid
  structured output, Router passed, but the Grader became too conservative.
- `deepseek_policy_candidate_grader_v3_run1.json` and `run2.json`: repeated v3 prompt runs used for
  stability and final component selection.
- `deepseek_policy_status.json`: machine-readable Stage 3E decision selecting the LLM Router and
  deterministic Grader/Rewriter.
- `context_budget_512_seed.json`, `context_budget_v1_seed.json` (768),
  `context_budget_1024_seed.json`, and `context_budget_1536_seed.json`: Stage 4B fixed-budget runs.
- `context_budget_sweep_v1_seed.json`: selects the smallest budget passing mandatory-preservation
  and relevant-document-recall gates.
- `context_coverage_1024_seed.json`: Stage 4C priority-versus-coverage A/B at the selected budget.
- `context_coverage_768_seed.json`: tighter stress-budget A/B exposing multi-constraint gains.
- `context_refinement_controlled_v1_seed.json`: Stage 4D controlled deduplication, conflict, and
  extractive-compression evaluation.
- `memory_isolation_controlled_v1.json`: Stage 4E isolation, lifecycle, privacy, and outage probes.
- `stage4_final_context_ablation_v1.json`: offline four-variant evidence-level Stage 4F comparison.
- `stage4_deepseek_answer_ablation_v1.json` through `v3.json`: retained negative/debugging runs.
- `stage4_deepseek_answer_ablation_v4_final.json`: final real DeepSeek answer A/B and selection.
- `planning_constraints_controlled_v1.json`: Stage 5A exact-output scenarios for deterministic
  budget, time, evidence, availability, opening-hours, and booking validation.
- `candidate_planning_controlled_v1.json`: Stage 5B expected-selection, safe-admission, and complete
  decision-trace evaluation for the explainable greedy baseline.
- `itinerary_repair_controlled_v1.json`: Stage 5C bounded repair, safe failure, unaffected-day
  preservation, and injected primary-repairer outage evaluation.
- `e2e_planning_hybrid_deterministic_v1.json`: Stage 5D real local Hybrid RRF deterministic baseline.
- `e2e_planning_deepseek_ab_v1.json`: retained strict-permutation failure with incomplete failure-cost
  telemetry; do not use it for final cost claims.
- `e2e_planning_deepseek_ab_v1_diagnostics.json`: corrected v1 telemetry proving shortlist-versus-
  permutation mismatch and 0.8 fallback.
- `e2e_planning_deepseek_ab_v2_final.json`: safe-shortlist contract with zero fallback.
- `e2e_planning_deepseek_ab_v3_final.json`: final repeated real A/B with post-hoc precision
  diagnostic; deterministic planner retained because expected-place lift was zero.
- `stage6ab_evaluation_audit_v1.json`: governed re-audit of the frozen Stage 5 report with a 3/2
  development/test breakdown, review-claim boundary, layered issue codes, and missing-telemetry
  disclosure.
- `stage6d_regression_gate_deterministic_v1.json`: the selected zero-provider planner passing all 17
  frozen release checks.
- `stage6d_regression_gate_deepseek_v1.json`: expected rejection of the paid ranker; quality lift is
  zero despite 895 tokens per case and roughly 877 ms mean provider latency.
- `stage6c_deepseek_judge_reference_v1.json`: 21-call AI-reference Judge calibration. All calls were
  valid, but agreement gates failed; provenance forces `reference_only` and Judge v1 is rejected.
- `stage7a_observability_drill_v1.json`: healthy, telemetry-outage, and retrieval-fallback
  drills covering trace correlation, attribute allowlisting, canary redaction, and sink independence.
- `stage7b_retrieval_resilience_v1.json`: deterministic breaker/cache state transitions, provider-call
  avoidance, dynamic stale rejection, bounded static fallback, and half-open recovery.
- `stage7c_checkpoint_idempotency_v1.json`: strict-serializer logical resume across a rebuilt graph,
  Planner call deduplication, completed-receipt replay, and checkpoint-outage safe failure.
- `stage7c2_durable_checkpoint_v1.json`: independent-process SQLite checkpoint resume and receipt
  replay with zero Planner calls in the recovery processes and owner-only database permissions.
- `stage7d_slo_outage_v1.json`: synthetic pre-release objectives covering recoverable three-component
  degradation, unrecoverable dual-retrieval safe failure, visibility, redaction, and local latency.
- `stage8a_index_publish_v1.json`: content-addressed snapshot, rejected-build quarantine,
  previous-version preservation, atomic promotion, rollback, and file-permission lifecycle drill.
- `stage8b_source_fetch_v1.json`: conditional revalidation, bounded transient recovery, dynamic-stale
  rejection, static bounded fallback, URL-policy enforcement, and sanitized diagnostics.
- `stage8c_incremental_ingestion_v1.json`: typed parse quarantine, authority/time conflict policy,
  unresolved suppression, affected-key recomputation, no-op detection, and failed-update isolation.
- `release_v1_audit.json`: Stage 9A audit of 15 hash-pinned evidence files and 18 semantic release
  claims. All 33 checks pass; the report explicitly limits the claim to an interview-grade pilot.
- `stage10a_pdf_ingestion_v1.json`: ten controlled official-PDF registry, payload-admission, and
  content-addressed snapshot checks. It is ingestion-security evidence, not a PDF parsing or RAG
  quality result.
- `stage11_runtime_replanning_v1.json`: first controlled Plan-Act-Observe-Replan comparison with
  layered failure attribution and bounded safe stop.
- `stage11_runtime_multistep_v1.json`: four-step candidate/availability/booking/travel trajectory;
  the agentic path recovers both intermediate failures while the fixed-plan baseline recovers none.
- `stage11_deepseek_runtime_v1_rejected.json` and `v2_rejected.json`: retained prompt/contract failure
  analyses; fallback-inclusive completion must not be read as raw model success.
- `stage11_deepseek_runtime_v3_final.json`: final real DeepSeek runtime-planner A/B. The model matches
  the controlled contract after canonicalization but is rejected for zero lift and 42.9% argument
  normalization.
- `release_v2_audit.json`: Stage 11D audit of 21 pinned artifacts and 25 semantic invariants. All 46
  checks pass; it preserves the older v1 release rather than rewriting its evidence boundary.
- `bm25_benchmark_v2_draft.json`, `dense_benchmark_v2_draft.json`, and
  `hybrid_benchmark_v2_draft.json`: Stage 12 re-test over 105 queries/35 intent clusters, with split
  metrics and deterministic cluster-bootstrap intervals.
- `reranked_benchmark_v2_draft.json`: expanded reranker ablation; Recall@5 remains below Hybrid RRF
  and mean local latency rises from about 2.82 ms to 216.30 ms.
- `answerability_admission_v2_draft.json`: development-tuned lexical evidence-admission candidate;
  test balanced accuracy is 0.878, but promotion is blocked because labels lack human review.
- `runtime_failure_matrix_v2_draft.json`: 34-case retry/replan/fallback matrix with exact contract,
  observation-reuse, and safe-stop results.

The Stage 1 seed is intentionally small and has no held-out split or abstention examples. These
reports support debugging and comparisons; they do not establish production quality or statistical
significance.

The Agentic policy labels are also small project-authored drafts. Their split prevents accidental
development-set tuning in code, but the test cases are not independently authored or blind. The
report is therefore a plumbing and error-analysis baseline, not a production accuracy claim.
